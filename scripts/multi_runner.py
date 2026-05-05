#!/usr/bin/env python3
"""
Multi-Instance Backfill Runner

A straightforward script to run multiple instances of the backfill script
without manually opening multiple terminals. Keeps it simple - no complex
health monitoring or configuration management.

Usage:
    # Start 3 workers with default settings
    python scripts/simple_multi_runner.py

    # Start 4 workers with custom batch size
    python scripts/simple_multi_runner.py --workers 4 --batch-size 10

    # Pass additional arguments to backfill scripts
    python scripts/simple_multi_runner.py --workers 3 --poll-interval 60 --include-retries
"""

import argparse
import subprocess
import signal
import sys
import time
from pathlib import Path
from typing import List

# Get the repository root directory
REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Run multiple backfill script instances',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # 3 workers, batch size 5
  %(prog)s --workers 4 --batch-size 10      # 4 workers, batch size 10
  %(prog)s --workers 2 --poll-interval 30   # 2 workers, 30s poll interval
  %(prog)s --include-retries --max-retries 5 # Include retry arguments
        """
    )

    # Multi-runner specific arguments
    parser.add_argument(
        '--workers',
        type=int,
        default=3,
        help='Number of worker processes to spawn (default: 3)'
    )

    # Arguments to pass through to backfill script
    parser.add_argument(
        '--batch-size',
        type=int,
        default=5,
        help='Number of items per batch (passed to each worker, default: 5)'
    )
    parser.add_argument(
        '--poll-interval',
        type=int,
        default=30,
        help='Seconds between polls when queue is empty (default: 30)'
    )
    parser.add_argument(
        '--idle-exit-after',
        type=int,
        default=0,
        help='Exit after N consecutive empty polls (default: 0 = never)'
    )
    parser.add_argument(
        '--include-retries',
        action='store_true',
        help='Include validation_failed items for retry'
    )
    parser.add_argument(
        '--max-retries',
        type=int,
        default=3,
        help='Max extraction attempts before permanent failure (default: 3)'
    )

    return parser.parse_args()


def build_worker_command(worker_id: int, args) -> List[str]:
    """Build the command to run a single worker."""
    cmd = [
        'uv', 'run', 'scripts/backfill_invoices_data/main.py',
        '--mode', 'queue',
        '--worker-id', str(worker_id),
        '--batch-size', str(args.batch_size),
        '--poll-interval', str(args.poll_interval),
        '--idle-exit-after', str(args.idle_exit_after),
        '--max-retries', str(args.max_retries)
    ]

    # Add optional flags
    if args.include_retries:
        cmd.append('--include-retries')

    return cmd


def main():
    """Main entry point."""
    args = parse_arguments()

    print(f"Starting {args.workers} backfill workers...")
    print(f"Batch size: {args.batch_size}")
    print(f"Poll interval: {args.poll_interval}s")
    print(f"Include retries: {args.include_retries}")
    print(f"Max retries: {args.max_retries}")
    print(f"Repository root: {REPO_ROOT}")
    print()

    # List to track spawned processes
    processes = []

    # Signal handler for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}. Shutting down workers...")
        for i, process in enumerate(processes):
            if process.poll() is None:  # Process is still running
                print(f"Terminating worker {i}...")
                process.terminate()

        # Wait a moment for graceful termination
        time.sleep(2)

        # Force kill if still running
        for i, process in enumerate(processes):
            if process.poll() is None:
                print(f"Force killing worker {i}...")
                process.kill()

        print("All workers stopped.")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

    try:
        # Spawn worker processes
        for worker_id in range(args.workers):
            cmd = build_worker_command(worker_id, args)
            print(f"Starting worker {worker_id}: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                cwd=REPO_ROOT,  # Set working directory to repository root
                stdout=None,    # Let workers handle their own logging
                stderr=None
            )
            processes.append(process)

        print(f"\n✓ All {args.workers} workers started successfully!")
        print("Press Ctrl+C to stop all workers")
        print()

        # Wait for all processes to complete
        while True:
            # Check if any processes have finished
            running_count = sum(1 for p in processes if p.poll() is None)

            if running_count == 0:
                print("All workers have finished.")
                break

            # Brief sleep to avoid busy waiting
            time.sleep(1)

    except KeyboardInterrupt:
        # This should be handled by signal_handler, but just in case
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        print(f"Error: {e}")
        # Clean up processes on error
        signal_handler(signal.SIGTERM, None)


if __name__ == "__main__":
    main()
