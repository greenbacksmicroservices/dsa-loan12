# 🚀 LIVE DEPLOYMENT GUIDE - this-my.elitedreamcapital.com

## **Deployment Information**
- **Domain**: `this-my.elitedreamcapital.com`
- **VPS Host**: `srv685.hstgr.io`
- **VPS IP**: `148.135.136.117`
- **Project Path**: `/var/www/dsa/dsa-loan12`
- **Database**: `u529002218_dream_captial1` (Hostinger MySQL)

---

## **STEP-BY-STEP DEPLOYMENT**

### **Step 1: Connect to VPS**
```bash
ssh user@srv685.hstgr.io
# Or use IP:
ssh user@148.135.136.117

# Navigate to project
cd /var/www/dsa/dsa-loan12
```

---

### **Step 2: Update Environment Files**
✅ **Already done in .env.production:**
- Updated ALLOWED_HOSTS for new domain
- Updated CSRF_TRUSTED_ORIGINS
- Updated CORS_ALLOWED_ORIGINS
- Updated EMAIL_HOST_USER

**Verify:**
```bash
cat .env.production | grep "ALLOWED_HOSTS"
# Should show: this-my.elitedreamcapital.com
```

---

### **Step 3: Set Up SSL Certificate (HTTPS)**

**Option A: Using Certbot (Recommended)**
```bash
# Install certbot
sudo apt update
sudo apt install certbot python3-certbot-nginx -y

# Generate SSL certificate
sudo certbot certonly --standalone -d this-my.elitedreamcapital.com -d www.this-my.elitedreamcapital.com

# Test auto-renewal
sudo certbot renew --dry-run
```

**Certificate Location:**
- Certificate: `/etc/letsencrypt/live/this-my.elitedreamcapital.com/fullchain.pem`
- Private Key: `/etc/letsencrypt/live/this-my.elitedreamcapital.com/privkey.pem`

---

### **Step 4: Configure Nginx (Reverse Proxy)**

**Create Nginx config:**
```bash
sudo nano /etc/nginx/sites-available/this-my.elitedreamcapital.com
```

**Paste this configuration:**
```nginx
server {
    listen 80;
    listen [::]:80;
    server_name this-my.elitedreamcapital.com www.this-my.elitedreamcapital.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name this-my.elitedreamcapital.com www.this-my.elitedreamcapital.com;

    # SSL Certificate
    ssl_certificate /etc/letsencrypt/live/this-my.elitedreamcapital.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/this-my.elitedreamcapital.com/privkey.pem;
    
    # SSL Configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Logging
    access_log /var/log/nginx/dsa_loan_access.log;
    error_log /var/log/nginx/dsa_loan_error.log;

    # Static files
    location /static/ {
        alias /var/www/dsa/dsa-loan12/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /var/www/dsa/dsa-loan12/media/;
        expires 7d;
    }

    # Pass to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

**Enable the site:**
```bash
sudo ln -s /etc/nginx/sites-available/this-my.elitedreamcapital.com /etc/nginx/sites-enabled/
sudo nginx -t  # Test configuration
sudo systemctl restart nginx
```

---

### **Step 5: Set Up Gunicorn Service**

**Create systemd service file:**
```bash
sudo nano /etc/systemd/system/dsa-loan.service
```

**Paste:**
```ini
[Unit]
Description=DSA Loan Django Application
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/var/www/dsa/dsa-loan12
Environment="PATH=/var/www/dsa/dsa-loan12/venv/bin"
EnvironmentFile=/var/www/dsa/dsa-loan12/.env.production
ExecStart=/var/www/dsa/dsa-loan12/venv/bin/gunicorn \
    --workers 3 \
    --worker-class sync \
    --bind 127.0.0.1:8000 \
    --timeout 60 \
    --access-logfile /var/log/dsa_loan_gunicorn_access.log \
    --error-logfile /var/log/dsa_loan_gunicorn_error.log \
    dsa_loan_management.wsgi:application
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable dsa-loan.service
sudo systemctl start dsa-loan.service
sudo systemctl status dsa-loan.service
```

---

### **Step 6: Prepare Django App**

**Activate virtual environment:**
```bash
cd /var/www/dsa/dsa-loan12
source venv/bin/activate
```

**Copy environment file:**
```bash
cp .env.production .env
```

**Collect static files:**
```bash
python manage.py collectstatic --noinput
```

**Run migrations:**
```bash
python manage.py migrate
```

**Create admin user (if needed):**
```bash
python manage.py createsuperuser
```

---

### **Step 7: Verify Live Deployment**

**Check if services are running:**
```bash
# Nginx
sudo systemctl status nginx

# Gunicorn
sudo systemctl status dsa-loan.service

# Check listening ports
sudo netstat -tuln | grep -E ':(80|443|8000)'
```

**Test the website:**
```bash
# Using curl
curl -I https://this-my.elitedreamcapital.com
# Should return: HTTP/2 200

# Check Django site
curl https://this-my.elitedreamcapital.com/admin/
```

**Test in browser:**
- Open: `https://this-my.elitedreamcapital.com`
- Login URL: `https://this-my.elitedreamcapital.com/admin-login/`
- Admin Panel: `https://this-my.elitedreamcapital.com/admin/`

---

### **Step 8: Database Setup (if migrating)**

**Backup current database:**
```bash
mysqldump -u u529002218_dream_captial1 -p u529002218_dream_captial1 > backup_$(date +%Y%m%d_%H%M%S).sql
```

**Verify database connection:**
```bash
mysql -h srv685.hstgr.io -u u529002218_dream_captial1 -p -e "SELECT VERSION();"
```

---

## **🆘 TROUBLESHOOTING**

### **Issue: SSL Certificate Error**
```bash
# Re-generate certificate
sudo certbot delete --cert-name this-my.elitedreamcapital.com
sudo certbot certonly --standalone -d this-my.elitedreamcapital.com
```

### **Issue: Connection Refused to Gunicorn**
```bash
# Restart Gunicorn
sudo systemctl restart dsa-loan.service
sudo journalctl -u dsa-loan.service -n 50
```

### **Issue: 502 Bad Gateway**
```bash
# Check Nginx logs
sudo tail -f /var/log/nginx/dsa_loan_error.log

# Check Gunicorn logs
sudo tail -f /var/log/dsa_loan_gunicorn_error.log
```

### **Issue: Database Connection Error**
```bash
# Test database from Django shell
python manage.py shell
>>> from django.db import connection
>>> print(connection.get_connection_params())
>>> exit()
```

---

## **📋 USER CREDENTIALS**

Default login accounts:
- **Admin**: admin@gmail.com / 123456789
- **SubAdmin**: subadmin@gmail.com / 123456789
- **Employee**: emp12@gmail.com / 123456789

**Login URLs:**
- Admin/SubAdmin: `/admin-login/`
- Employee/Agent: `/login/`

---

## **✅ DEPLOYMENT CHECKLIST**

- [ ] SSH connection working
- [ ] .env.production updated with new domain
- [ ] SSL certificate generated
- [ ] Nginx configured and enabled
- [ ] Gunicorn service created and enabled
- [ ] Static files collected
- [ ] Migrations run
- [ ] Database verified
- [ ] Site accessible via HTTPS
- [ ] Admin panel working
- [ ] Users can login

---

## **🔧 POST-DEPLOYMENT**

### **Monitor Logs:**
```bash
# Nginx access logs
tail -f /var/log/nginx/dsa_loan_access.log

# Gunicorn logs
sudo tail -f /var/log/dsa_loan_gunicorn_error.log

# Django logs
tail -f /var/www/dsa/dsa-loan12/gunicorn.log
```

### **Auto-renew SSL:**
```bash
# Certbot handles renewal automatically
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

### **Update Code:**
```bash
cd /var/www/dsa/dsa-loan12
git pull origin main
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart dsa-loan.service
```

---

**🎉 Your project is now live!**
- Domain: `https://this-my.elitedreamcapital.com`
- Admin: `https://this-my.elitedreamcapital.com/admin-login/`
