# 🚀 QUICK DEPLOYMENT - 5 Minutes
## this-my.elitedreamcapital.com

### **Prerequisites**
```bash
SSH to VPS:
ssh user@srv685.hstgr.io
cd /var/www/dsa/dsa-loan12
```

### **Commands (Run in order)**

#### 1️⃣ **Copy Environment File**
```bash
cp .env.production .env
```

#### 2️⃣ **Generate SSL Certificate** (if not exists)
```bash
sudo certbot certonly --standalone -d this-my.elitedreamcapital.com -d www.this-my.elitedreamcapital.com
```

#### 3️⃣ **Setup Nginx Config**
```bash
# Create config (see details in LIVE_DEPLOYMENT_GUIDE.md)
sudo nano /etc/nginx/sites-available/this-my.elitedreamcapital.com

# Enable and test
sudo ln -s /etc/nginx/sites-available/this-my.elitedreamcapital.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 4️⃣ **Setup Gunicorn Service**
```bash
# Create service file (see details in LIVE_DEPLOYMENT_GUIDE.md)
sudo nano /etc/systemd/system/dsa-loan.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable dsa-loan.service
sudo systemctl start dsa-loan.service
```

#### 5️⃣ **Django Setup**
```bash
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
deactivate
```

#### 6️⃣ **Verify Live**
```bash
curl -I https://this-my.elitedreamcapital.com
# Should return: HTTP/2 200

# Check all services
systemctl status nginx
systemctl status dsa-loan.service
```

### **🎯 Access Your Site**
```
https://this-my.elitedreamcapital.com
https://this-my.elitedreamcapital.com/admin-login/
```

### **📊 Monitor**
```bash
# Nginx logs
tail -f /var/log/nginx/dsa_loan_access.log

# Gunicorn logs
sudo tail -f /var/log/dsa_loan_gunicorn_error.log

# Service status
systemctl status dsa-loan.service
```

### **❌ Quick Fixes**
```bash
# Restart Gunicorn
sudo systemctl restart dsa-loan.service

# Reload Nginx
sudo systemctl reload nginx

# Check logs for errors
sudo journalctl -u dsa-loan.service -n 100
```

---
**Read LIVE_DEPLOYMENT_GUIDE.md for detailed step-by-step instructions**
