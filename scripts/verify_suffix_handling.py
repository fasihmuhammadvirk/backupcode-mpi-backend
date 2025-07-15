#!/usr/bin/env python3
"""
Suffix Handling Verification Script

This script checks the current state of suffix handling in the codebase
and identifies any remaining suffix cleaning logic that needs to be removed.
"""

import os
import re
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_file_for_suffix_patterns(file_path):
    """Check a file for suffix-related patterns."""
    issues = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
        
        # Patterns to look for
        patterns = [
            (r'clean_supplier_suffix', 'clean_supplier_suffix function call'),
            (r'restore_suffix', 'restore_suffix function call'),
            (r'item_code_with_suffix', 'item_code_with_suffix property usage'),
            (r'clean_suffix', 'clean_suffix function call'),
            (r'compare_item_codes_with_cleaning', 'compare_item_codes_with_cleaning function'),
            (r'bulk_restore_suffixes', 'bulk_restore_suffixes function'),
            (r'should_restore_suffix', 'should_restore_suffix function'),
            (r'remove.*suffix', 'suffix removal logic'),
            (r'strip.*suffix', 'suffix stripping logic'),
            (r'-\s*[BWYSGFPA]\s*$', 'suffix pattern matching'),
            (r'-\s*[BWYSGFPA](\s|$)', 'suffix pattern matching'),
        ]
        
        for line_num, line in enumerate(lines, 1):
            for pattern, description in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append({
                        'line': line_num,
                        'content': line.strip(),
                        'description': description,
                        'pattern': pattern
                    })
        
        return issues
    
    except Exception as e:
        return [{'line': 0, 'content': f'Error reading file: {e}', 'description': 'File read error', 'pattern': ''}]


def scan_directory(directory):
    """Scan a directory for Python files and check for suffix patterns."""
    results = {}
    
    for root, dirs, files in os.walk(directory):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', 'node_modules', 'venv', 'env']]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                issues = check_file_for_suffix_patterns(file_path)
                if issues:
                    results[file_path] = issues
    
    return results


def main():
    """Main function to run the verification."""
    print("🔍 Suffix Handling Verification")
    print("=" * 50)
    
    # Scan the mpi_backend directory
    backend_dir = "mpi_backend"
    if not os.path.exists(backend_dir):
        print(f"❌ Directory {backend_dir} not found")
        return
    
    print(f"Scanning {backend_dir} directory...")
    results = scan_directory(backend_dir)
    
    # Scan scripts directory
    scripts_dir = "scripts"
    if os.path.exists(scripts_dir):
        print(f"Scanning {scripts_dir} directory...")
        script_results = scan_directory(scripts_dir)
        results.update(script_results)
    
    if not results:
        print("✅ No suffix cleaning logic found!")
        print("The codebase appears to be clean of suffix handling logic.")
        return
    
    print(f"\n❌ Found {len(results)} files with suffix-related patterns:")
    print("=" * 50)
    
    total_issues = 0
    for file_path, issues in results.items():
        print(f"\n📁 {file_path}")
        print("-" * len(file_path))
        
        for issue in issues:
            total_issues += 1
            print(f"  Line {issue['line']}: {issue['description']}")
            print(f"    Content: {issue['content']}")
            print()
    
    print(f"\n📊 Summary:")
    print(f"  Files with issues: {len(results)}")
    print(f"  Total issues found: {total_issues}")
    
    print(f"\n🔧 Recommendations:")
    print("  1. Review each file listed above")
    print("  2. Remove or update suffix cleaning logic")
    print("  3. Ensure item codes are stored and displayed with full suffixes")
    print("  4. Test the application after making changes")
    
    # Check for specific critical patterns
    critical_patterns = [
        'clean_supplier_suffix',
        'item_code_with_suffix',
        'restore_suffix'
    ]
    
    critical_files = []
    for file_path, issues in results.items():
        for issue in issues:
            if any(pattern in issue['description'].lower() for pattern in critical_patterns):
                critical_files.append(file_path)
                break
    
    if critical_files:
        print(f"\n🚨 Critical files that need immediate attention:")
        for file_path in set(critical_files):
            print(f"  - {file_path}")


if __name__ == "__main__":
    main() 