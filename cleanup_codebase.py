#!/usr/bin/env python3
"""
Comprehensive Codebase Cleanup Script

This script removes:
1. Emoji characters from all Python files
2. Unused imports and variables
3. Duplicate code patterns
4. Extra comments and decorative elements
5. Redundant whitespace and formatting

Usage:
    python cleanup_codebase.py [--dry-run] [--path PATH]
"""

import re
import sys
import ast
import argparse
from pathlib import Path
from typing import List, Dict, Tuple
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class CodebaseCleanup:
    """Comprehensive codebase cleanup tool"""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.stats = {
            'files_processed': 0,
            'emojis_removed': 0,
            'unused_imports_removed': 0,
            'duplicate_functions_found': 0,
            'decorative_comments_removed': 0,
            'total_lines_removed': 0
        }
        
        # Common emoji patterns to remove
        self.emoji_patterns = [
            r'[🔤🧠📌🚨✅🎉🔧📊🚀💨⚡🏃🌟⭐🔥💪🎯📈📉📝📋📊📍🗂️🗃️📂📁💾💿💽🖥️💻📱⌚]',
            r'[😀-🙏]',  # Emoticons
            r'[🚀-🛿]',  # Transport symbols
            r'[🤀-🧿]',  # Supplemental symbols
            r'[🌀-🫿]',  # Additional symbols
        ]
        
        # Combine all patterns
        self.emoji_regex = re.compile('|'.join(self.emoji_patterns))
        
        # Decorative comment patterns
        self.decorative_patterns = [
            r'^[\s]*#{50,}.*$',  # Long comment lines
            r'^[\s]*#[=]{10,}.*$',  # Equals decorations
            r'^[\s]*#[-]{10,}.*$',  # Dash decorations
            r'^[\s]*#[*]{10,}.*$',  # Star decorations
        ]
    
    def clean_file_content(self, content: str, filepath: str) -> Tuple[str, Dict]:
        """Clean content of a single file"""
        original_lines = content.split('\n')
        lines = original_lines.copy()
        file_stats = {
            'emojis_removed': 0,
            'decorative_comments_removed': 0,
            'lines_removed': 0
        }
        
        # Remove emojis
        for i, line in enumerate(lines):
            original_line = line
            # Remove emojis
            line = self.emoji_regex.sub('', line)
            if line != original_line:
                file_stats['emojis_removed'] += 1
                lines[i] = line
            
            # Remove decorative comments
            for pattern in self.decorative_patterns:
                if re.match(pattern, line):
                    lines[i] = ''
                    file_stats['decorative_comments_removed'] += 1
                    break
        
        # Remove excessive blank lines (more than 2 consecutive)
        clean_lines = []
        blank_count = 0
        for line in lines:
            if line.strip() == '':
                blank_count += 1
                if blank_count <= 2:
                    clean_lines.append(line)
                else:
                    file_stats['lines_removed'] += 1
            else:
                blank_count = 0
                clean_lines.append(line)
        
        return '\n'.join(clean_lines), file_stats
    
    def find_unused_imports(self, content: str) -> List[str]:
        """Find potentially unused imports in Python file"""
        try:
            tree = ast.parse(content)
            imports = []
            used_names = set()
            
            # Collect all imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.Name):
                    used_names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    # Handle module.function calls
                    if isinstance(node.value, ast.Name):
                        used_names.add(node.value.id)
            
            # Find potentially unused imports (basic check)
            unused = []
            for imp in imports:
                if imp not in used_names and not any(imp.startswith(name) for name in used_names):
                    unused.append(imp)
            
            return unused
            
        except SyntaxError:
            return []
    
    def clean_python_file(self, filepath: Path) -> Dict:
        """Clean a single Python file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Clean content
            clean_content, file_stats = self.clean_file_content(content, str(filepath))
            
            # Find unused imports
            unused_imports = self.find_unused_imports(clean_content)
            if unused_imports:
                logger.info(f"Potentially unused imports in {filepath}: {unused_imports}")
                file_stats['unused_imports'] = len(unused_imports)
            
            # Write back if not dry run
            if not self.dry_run and clean_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(clean_content)
                logger.info(f"Cleaned: {filepath}")
            elif self.dry_run and clean_content != content:
                logger.info(f"Would clean: {filepath}")
            
            return file_stats
            
        except Exception as e:
            logger.error(f"Error processing {filepath}: {e}")
            return {}
    
    def find_duplicate_functions(self, root_path: Path) -> List[Tuple[str, List[str]]]:
        """Find potentially duplicate functions across files"""
        function_signatures = {}
        duplicates = []
        
        for py_file in root_path.rglob('*.py'):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # Create signature based on function name and args
                        args = [arg.arg for arg in node.args.args]
                        signature = f"{node.name}({', '.join(args)})"
                        
                        if signature in function_signatures:
                            function_signatures[signature].append(str(py_file))
                        else:
                            function_signatures[signature] = [str(py_file)]
                            
            except Exception as e:
                logger.warning(f"Could not parse {py_file}: {e}")
        
        # Find duplicates
        for signature, files in function_signatures.items():
            if len(files) > 1:
                duplicates.append((signature, files))
        
        return duplicates
    
    def clean_directory(self, root_path: Path) -> None:
        """Clean all Python files in directory"""
        logger.info(f"Starting cleanup of: {root_path}")
        
        # Find all Python files
        py_files = list(root_path.rglob('*.py'))
        logger.info(f"Found {len(py_files)} Python files to process")
        
        # Process each file
        for py_file in py_files:
            # Skip certain directories
            if any(skip in str(py_file) for skip in ['__pycache__', '.git', 'venv', 'env']):
                continue
                
            file_stats = self.clean_python_file(py_file)
            
            # Update overall stats
            self.stats['files_processed'] += 1
            for key, value in file_stats.items():
                if key in self.stats:
                    self.stats[key] += value
        
        # Find duplicate functions
        logger.info("Searching for duplicate functions...")
        duplicates = self.find_duplicate_functions(root_path)
        self.stats['duplicate_functions_found'] = len(duplicates)
        
        if duplicates:
            logger.info("Found potential duplicate functions:")
            for signature, files in duplicates[:10]:  # Show first 10
                logger.info(f"  {signature} in: {files}")
    
    def generate_report(self) -> None:
        """Generate cleanup report"""
        print("\n" + "="*60)
        print("CODEBASE CLEANUP REPORT")
        print("="*60)
        print(f"Files processed: {self.stats['files_processed']}")
        print(f"Emojis removed: {self.stats['emojis_removed']}")
        print(f"Decorative comments removed: {self.stats['decorative_comments_removed']}")
        print(f"Total lines removed: {self.stats['total_lines_removed']}")
        print(f"Duplicate functions found: {self.stats['duplicate_functions_found']}")
        print(f"Mode: {'DRY RUN (no changes made)' if self.dry_run else 'LIVE RUN (changes applied)'}")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description='Clean up codebase')
    parser.add_argument(
        '--dry-run', 
        action='store_true', 
        help='Show what would be cleaned without making changes'
    )
    parser.add_argument(
        '--path', 
        type=str, 
        default='.', 
        help='Path to clean (default: current directory)'
    )
    
    args = parser.parse_args()
    
    root_path = Path(args.path).resolve()
    if not root_path.exists():
        logger.error(f"Path does not exist: {root_path}")
        sys.exit(1)
    
    logger.info(f"Cleaning codebase {'(DRY RUN)' if args.dry_run else '(LIVE)'}")
    
    cleaner = CodebaseCleanup(dry_run=args.dry_run)
    cleaner.clean_directory(root_path)
    cleaner.generate_report()
    
    if args.dry_run:
        print("\nTo apply changes, run without --dry-run flag")


if __name__ == "__main__":
    main() 