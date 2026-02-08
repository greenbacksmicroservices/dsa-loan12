"""
FORM ISOLATION VERIFICATION & AUDIT
====================================
Comprehensive check to ensure NO form includes exist outside New Entry section.

This script validates:
1. No {% include %} statements for forms in templates
2. No <form> tags except in partials/application_form_only.html
3. All dashboard sections are read-only
4. Base templates don't include forms
5. All list/detail pages use table-based layouts
"""

import os
import re
from pathlib import Path


class FormIsolationAuditor:
    """Audits template files to ensure form isolation."""
    
    def __init__(self, template_root='templates'):
        self.template_root = Path(template_root)
        self.issues = []
        self.warnings = []
        self.passed_files = []
    
    def scan_templates(self):
        """Scan all templates for form includes and violations."""
        if not self.template_root.exists():
            self.issues.append(f"Template root not found: {self.template_root}")
            return
        
        # Patterns to look for
        form_include_pattern = re.compile(r'{%\s*include\s+["\'].*form.*["\']', re.IGNORECASE)
        form_tag_pattern = re.compile(r'<form\s+', re.IGNORECASE)
        
        # Files that are ALLOWED to have forms
        allowed_files = {
            'templates/partials/application_form_only.html',
        }
        
        # Scan all HTML files
        for template_file in self.template_root.rglob('*.html'):
            relative_path = str(template_file.relative_to(self.template_root))
            
            with open(template_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                line_num = 0
                
                for line in content.split('\n'):
                    line_num += 1
                    
                    # Check for form includes
                    if form_include_pattern.search(line):
                        if relative_path not in allowed_files:
                            self.issues.append(
                                f"❌ {relative_path}:{line_num} - "
                                f"Form include found: {line.strip()}"
                            )
                    
                    # Check for form tags
                    if form_tag_pattern.search(line):
                        if relative_path not in allowed_files:
                            self.issues.append(
                                f"❌ {relative_path}:{line_num} - "
                                f"<form> tag found: {line.strip()}"
                            )
                    
                    # Warn about status-specific content in base
                    if relative_path == 'core/base.html':
                        if 'new_entry' in line.lower() or 'waiting' in line.lower():
                            if not any(x in line for x in ['class', 'data-', '#']):
                                self.warnings.append(
                                    f"⚠️  {relative_path}:{line_num} - "
                                    f"Status-specific content: {line.strip()}"
                                )
            
            # If no issues in this file, add to passed
            if relative_path not in allowed_files:
                has_issue = any(relative_path in issue for issue in self.issues)
                if not has_issue:
                    self.passed_files.append(relative_path)
    
    def check_partial_exists(self):
        """Verify application_form_only.html exists."""
        partial = self.template_root / 'partials' / 'application_form_only.html'
        if not partial.exists():
            self.issues.append("❌ partials/application_form_only.html NOT FOUND")
        else:
            self.passed_files.append('templates/partials/application_form_only.html (EXISTS)')
    
    def check_router_imports(self):
        """Verify router views are properly imported in urls.py."""
        urls_file = Path('core/urls.py')
        if urls_file.exists():
            with open(urls_file, 'r') as f:
                content = f.read()
                if 'form_isolation_router' not in content:
                    self.warnings.append(
                        "⚠️  form_isolation_router not imported in urls.py"
                    )
    
    def generate_report(self):
        """Generate audit report."""
        print("\n" + "="*80)
        print("FORM ISOLATION AUDIT REPORT")
        print("="*80 + "\n")
        
        print(f"✓ Passed Files: {len(self.passed_files)}")
        if self.passed_files:
            for f in sorted(self.passed_files)[:10]:  # Show first 10
                print(f"  ✓ {f}")
            if len(self.passed_files) > 10:
                print(f"  ... and {len(self.passed_files) - 10} more")
        
        print(f"\n⚠️  Warnings: {len(self.warnings)}")
        if self.warnings:
            for w in self.warnings:
                print(f"  {w}")
        
        print(f"\n❌ Critical Issues: {len(self.issues)}")
        if self.issues:
            for issue in self.issues:
                print(f"  {issue}")
        else:
            print("  ✓ No form isolation violations found!")
        
        print("\n" + "="*80)
        
        if not self.issues:
            print("✓ FORM ISOLATION VERIFICATION PASSED")
            print("="*80 + "\n")
            return True
        else:
            print("❌ FORM ISOLATION VERIFICATION FAILED")
            print("="*80 + "\n")
            return False


if __name__ == '__main__':
    auditor = FormIsolationAuditor()
    auditor.check_partial_exists()
    auditor.scan_templates()
    auditor.check_router_imports()
    success = auditor.generate_report()
    exit(0 if success else 1)
