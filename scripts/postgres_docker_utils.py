import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class PostgresDockerUtils:
    """
    Utility class for running PostgreSQL client tools in Docker containers.

    Provides Docker fallback when native PostgreSQL tools (pg_dump, psql,
    pg_restore) are not installed locally. Handles network configuration,
    volume mounting, and environment variable setup.
    """

    def __init__(self,
                 db_host: str,
                 db_port: str,
                 db_name: str,
                 db_user: str,
                 db_password: str,
                 docker_image: str = 'postgres:16'):
        """
        Initialize PostgreSQL Docker utilities.

        Args:
            db_host: PostgreSQL host (hostname or IP)
            db_port: PostgreSQL port
            db_name: Database name
            db_user: Database user
            db_password: Database password
            docker_image: Docker image to use

        Usage:
            from scripts.postgres_docker_utils import PostgresDockerUtils

                 utils = PostgresDockerUtils(
                         db_host='localhost',
                         db_port='5432',
                         db_name='mydb',
                         db_user='postgres',
                         db_password='secret',
                         docker_image='postgres:16'
                         )

                 # Check Docker availability
                 available, error_msg = utils.check_docker_availability()

                 # Build Docker command
                 cmd = utils.build_docker_command(pg_command='psql', pg_args=['-c', 'SELECT version();'])
        """
        self.db_host = db_host
        self.db_port = db_port
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password
        self.docker_image = docker_image
        self.docker_network = None

    def check_docker_availability(self) -> Tuple[bool, str]:
        """
        Check if Docker is available and can run PostgreSQL containers.

        Verifies:
        1. Docker command exists
        2. Docker daemon is running
        3. PostgreSQL image is available (pulls if needed)

        Returns:
            Tuple[bool, str]: (available, error_message)
        """
        # Check docker command exists
        if not shutil.which('docker'):
            return False, "Docker command not found"

        # Check docker daemon is running
        try:
            subprocess.run(
                ['docker', 'info'],
                capture_output=True,
                check=True,
                timeout=5
            )
        except subprocess.TimeoutExpired:
            return False, "Docker daemon not responding (timeout)"
        except subprocess.CalledProcessError as e:
            return False, f"Docker daemon not running: {e}"
        except Exception as e:
            return False, f"Docker availability check failed: {e}"

        # Check/pull PostgreSQL image
        try:
            result = subprocess.run(
                ['docker', 'images', '-q', self.docker_image],
                capture_output=True,
                text=True,
                check=True
            )

            if not result.stdout.strip():
                logger.info(f"PostgreSQL Docker image '{self.docker_image}' not found, pulling...")
                logger.info("This may take a few minutes on first run...")
                subprocess.run(
                    ['docker', 'pull', self.docker_image],
                    check=True,
                    timeout=300
                )
                logger.info(f"Successfully pulled {self.docker_image}")
        except subprocess.TimeoutExpired:
            return False, f"Timeout pulling Docker image {self.docker_image}"
        except Exception as e:
            return False, f"Cannot access PostgreSQL Docker image: {e}"

        return True, ""

    def get_docker_network_name(self) -> Optional[str]:
        """
        Detect the Docker network to use for database connectivity.

        Priority:
        1. If db_host is a container name, find its network
        2. Look for common postgres network names
        3. Use bridge network as fallback

        Returns:
            Network name or None for host networking
        """
        try:
            # Check if db_host is a Docker container
            result = subprocess.run(
                ['docker', 'inspect', self.db_host,
                 '--format', '{{range $net, $conf := .NetworkSettings.Networks}}{{$net}}{{end}}'],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0 and result.stdout.strip():
                network = result.stdout.strip()
                logger.info(f"Detected database container network: {network}")
                return network

            # Check for common network names
            for network_name in ['mpi-backend_postgres_ntw', 'postgres_ntw', 'mpi-backend_default']:
                result = subprocess.run(
                    ['docker', 'network', 'inspect', network_name],
                    capture_output=True,
                    check=False
                )
                if result.returncode == 0:
                    logger.info(f"Using Docker network: {network_name}")
                    return network_name

            # Fallback to bridge
            logger.warning("No custom network found, using bridge")
            return 'bridge'

        except Exception as e:
            logger.warning(f"Error detecting Docker network: {e}, using bridge")
            return 'bridge'

    def determine_database_location(self) -> str:
        """
        Determine where the database is located.

        Returns:
            'host', 'container', or 'remote'
        """
        if self.db_host in ['localhost', '127.0.0.1', '0.0.0.0']:
            return 'host'

        # Check if db_host is a Docker container
        try:
            result = subprocess.run(
                ['docker', 'inspect', self.db_host],
                capture_output=True,
                check=False
            )
            if result.returncode == 0:
                return 'container'
        except Exception:
            pass

        return 'remote'

    def build_docker_command(self,
                           pg_command: str,
                           pg_args: List[str],
                           volume_mappings: Optional[List[Tuple[str, str]]] = None,
                           override_pgdatabase: Optional[str] = None) -> List[str]:
        """
        Build Docker command to execute PostgreSQL tool.

        Args:
            pg_command: PostgreSQL command (pg_dump, psql, pg_restore)
            pg_args: Arguments for the PostgreSQL command
            volume_mappings: List of (host_path, container_path) tuples
            override_pgdatabase: Override PGDATABASE env var (e.g., 'postgres' for admin ops)

        Returns:
            Complete docker run command as list
        """
        docker_cmd = [
            'docker', 'run',
            '--rm',  # Remove container after execution
            '-i',    # Keep STDIN open for interactive operations
        ]

        # Add volume mappings
        if volume_mappings:
            for host_path, container_path in volume_mappings:
                docker_cmd.extend(['-v', f'{host_path}:{container_path}'])

        # Determine network configuration based on database location
        db_location = self.determine_database_location()

        if db_location == 'host':
            # Database on localhost - use host networking
            docker_cmd.extend(['--network', 'host'])
            logger.debug("Using host network mode (database on localhost)")
        elif db_location == 'container':
            # Database in Docker container - join its network
            if self.docker_network:
                docker_cmd.extend(['--network', self.docker_network])
                logger.debug(f"Using network '{self.docker_network}' (database in container)")
        else:
            # Remote database - use bridge network
            docker_cmd.extend(['--network', 'bridge'])
            logger.debug("Using bridge network (remote database)")

        # Set environment variables for PostgreSQL connection
        docker_cmd.extend([
            '-e', f'PGPASSWORD={self.db_password}',
            '-e', f'PGHOST={self.db_host}',
            '-e', f'PGPORT={self.db_port}',
            '-e', f'PGUSER={self.db_user}',
            '-e', f'PGDATABASE={override_pgdatabase if override_pgdatabase else self.db_name}'
        ])

        # PostgreSQL image and command
        docker_cmd.extend([self.docker_image, pg_command])

        # Add PostgreSQL command arguments
        docker_cmd.extend(pg_args)

        return docker_cmd

    def prepare_path_for_docker(self, local_path: Path) -> Tuple[str, str, str]:
        """
        Prepare file path for Docker volume mounting.

        Args:
            local_path: Path on host system

        Returns:
            Tuple[str, str, str]: (host_dir, container_dir, container_file_path)
        """
        # Convert to absolute path
        abs_path = local_path.resolve()

        # Use /backup as the container mount point
        container_dir = '/backup'
        container_file_path = f'{container_dir}/{abs_path.name}'

        # Return parent directory for mounting
        return str(abs_path.parent), container_dir, container_file_path
