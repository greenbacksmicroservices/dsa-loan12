#!/usr/bin/env python3
"""
Live Deployment Script for this-my.elitedreamcapital.com
Automates the deployment process for DSA Loan Admin Panel
"""

import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path("/var/www/dsa/dsa-loan12")
DOMAIN = "this-my.elitedreamcapital.com"
VPS_IP = "148.135.136.117"
GUNICORN_PORT = 8000

def print_header(text):
    """Print a formatted header"""
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60 + "\n")

def run_command(cmd, description, check=True):
    """Run a shell command and print the result"""
    print(f"📌 {description}")
    print(f"   $ {cmd}\n")
    try:
        result = subprocess.run(cmd, shell=True, check=check, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"❌ ERROR: {e}")
        if e.stderr:
            print(f"   {e.stderr}")
        return False

def main():
    print_header("🚀 DSA Loan Live Deployment Script")
    print(f"Domain: {DOMAIN}")
    print(f"VPS IP: {VPS_IP}")
    print(f"Project: {PROJECT_ROOT}\n")

    # Check if running as root or with sudo
    if os.geteuid() != 0:
        print("⚠️  This script requires sudo privileges!")
        print("Run: sudo python3 deploy_live.py\n")
        sys.exit(1)

    # Step 1: Environment Setup
    print_header("STEP 1: Environment Setup")
    
    os.chdir(PROJECT_ROOT)
    
    if not run_command(
        "test -f .env.production",
        "Checking .env.production exists"
    ):
        print("❌ .env.production not found!")
        sys.exit(1)
    
    run_command(
        "cp .env.production .env",
        "Copy .env.production to .env"
    )

    # Step 2: Django Setup
    print_header("STEP 2: Django Setup")
    
    venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
    if not venv_python.exists():
        print("❌ Virtual environment not found!")
        print("   Create it first: python3 -m venv venv")
        sys.exit(1)

    run_command(
        f"source {PROJECT_ROOT}/venv/bin/activate && python manage.py migrate",
        "Run Django migrations"
    )

    run_command(
        f"source {PROJECT_ROOT}/venv/bin/activate && python manage.py collectstatic --noinput",
        "Collect static files"
    )

    # Step 3: SSL Certificate
    print_header("STEP 3: SSL Certificate Setup")
    
    cert_path = f"/etc/letsencrypt/live/{DOMAIN}/fullchain.pem"
    if not Path(cert_path).exists():
        print(f"⚠️  SSL certificate not found at {cert_path}")
        print("   Generating new certificate...\n")
        
        run_command(
            f"certbot certonly --standalone -d {DOMAIN} -d www.{DOMAIN}",
            "Generate SSL certificate with Certbot"
        )
    else:
        print(f"✅ SSL certificate found: {cert_path}\n")

    # Step 4: Nginx Configuration
    print_header("STEP 4: Nginx Configuration")
    
    nginx_config = f"/etc/nginx/sites-available/{DOMAIN}"
    nginx_enabled = f"/etc/nginx/sites-enabled/{DOMAIN}"
    
    if not Path(nginx_config).exists():
        print(f"Creating Nginx config: {nginx_config}\n")
        # Nginx config creation would be handled separately
        print("⚠️  Please create Nginx config manually")
        print(f"   See LIVE_DEPLOYMENT_GUIDE.md for template")
    else:
        print(f"✅ Nginx config exists: {nginx_config}\n")
    
    if Path(nginx_config).exists():
        if not Path(nginx_enabled).exists():
            run_command(
                f"ln -s {nginx_config} {nginx_enabled}",
                "Enable Nginx site"
            )
        
        run_command(
            "nginx -t",
            "Test Nginx configuration"
        )
        
        run_command(
            "systemctl reload nginx",
            "Reload Nginx"
        )

    # Step 5: Gunicorn Service
    print_header("STEP 5: Gunicorn Systemd Service")
    
    service_file = "/etc/systemd/system/dsa-loan.service"
    if not Path(service_file).exists():
        print(f"⚠️  Systemd service not found: {service_file}")
        print("   Please create it manually (see LIVE_DEPLOYMENT_GUIDE.md)\n")
    else:
        run_command(
            "systemctl daemon-reload",
            "Reload systemd daemon"
        )
        
        run_command(
            "systemctl enable dsa-loan.service",
            "Enable Gunicorn service"
        )
        
        run_command(
            "systemctl start dsa-loan.service",
            "Start Gunicorn service"
        )
        
        run_command(
            "systemctl status dsa-loan.service",
            "Check Gunicorn service status"
        )

    # Step 6: Verification
    print_header("STEP 6: Verification")
    
    run_command(
        "systemctl status nginx",
        "Check Nginx status"
    )
    
    run_command(
        f"netstat -tuln | grep -E ':(80|443|{GUNICORN_PORT})'",
        "Check listening ports"
    )
    
    run_command(
        f"curl -I https://{DOMAIN}/",
        "Test HTTPS connection"
    )

    # Summary
    print_header("✅ Deployment Complete!")
    
    print(f"""
🎉 Your project is now live!

📍 Access Points:
   • Main Site:    https://{DOMAIN}
   • Admin Panel:  https://{DOMAIN}/admin-login/
   • Admin:        https://{DOMAIN}/admin/

🔐 Login Credentials:
   • Admin:        admin@gmail.com / 123456789
   • SubAdmin:     subadmin@gmail.com / 123456789
   • Employee:     emp12@gmail.com / 123456789

📊 Monitoring:
   • Nginx logs:       tail -f /var/log/nginx/dsa_loan_access.log
   • Gunicorn logs:    sudo tail -f /var/log/dsa_loan_gunicorn_error.log
   • Service status:   systemctl status dsa-loan.service

🔄 Updates:
   • Pull updates:     cd {PROJECT_ROOT} && git pull
   • Restart service:  sudo systemctl restart dsa-loan.service
   • Renew SSL:        sudo certbot renew --dry-run
    """)

if __name__ == "__main__":
    main()
