/**
 * Admin Panel Real-Time Data Sync Module
 * Handles real-time updates for dashboard, processing requests, and employee data
 */

class AdminDataManager {
    constructor() {
        this.apiBaseUrl = '/api';
        this.updateInterval = 30000; // 30 seconds
        this.websocketConnected = false;
        this.retryCount = 0;
        this.maxRetries = 5;
        this.init();
    }

    init() {
        console.log('[AdminDataManager] Initializing...');
        this.setupEventListeners();
        this.loadInitialData();
        this.startAutoRefresh();
    }

    setupEventListeners() {
        // Listen for visibility changes to pause/resume updates
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.pauseAutoRefresh();
            } else {
                this.startAutoRefresh();
            }
        });
    }

    /**
     * Load all dashboard statistics
     */
    async loadDashboardStats() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/admin-stats/`, {
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json',
                }
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            if (data.success) {
                this.updateDashboardUI(data.stats);
                this.retryCount = 0; // Reset retry count on success
            }
        } catch (error) {
            console.error('[AdminDataManager] Error loading dashboard stats:', error);
            this.handleApiError(error);
        }
    }

    /**
     * Update dashboard UI with stats
     */
    updateDashboardUI(stats) {
        const mapping = {
            'stat-new-entry': stats.new_entry || stats.new_entries || 0,
            'stat-waiting': stats.processing || stats.waiting || 0,
            'stat-follow-up': stats.processing || stats.follow_up || 0,
            'stat-approved': stats.approved || 0,
            'stat-rejected': stats.rejected || 0,
            'stat-disbursed': stats.disbursed || 0,
        };

        for (const [elementId, value] of Object.entries(mapping)) {
            const element = document.getElementById(elementId);
            if (element) {
                // Animate count change
                const currentValue = parseInt(element.textContent) || 0;
                if (currentValue !== value) {
                    element.style.transition = 'all 0.3s ease';
                    element.style.transform = 'scale(1.1)';
                    element.textContent = value;
                    setTimeout(() => {
                        element.style.transform = 'scale(1)';
                    }, 100);
                }
            }
        }
    }

    /**
     * Load employees list
     */
    async loadEmployees(page = 1, perPage = 10) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/employees/?page=${page}&per_page=${perPage}`, {
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json',
                }
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            if (data.success) {
                return data;
            }
        } catch (error) {
            console.error('[AdminDataManager] Error loading employees:', error);
            throw error;
        }
    }

    /**
     * Load processing requests
     */
    async loadProcessingRequests(filters = {}) {
        try {
            const url = new URL(`${this.apiBaseUrl}/processing-requests/`, window.location.origin);
            Object.entries(filters).forEach(([key, value]) => {
                if (value) url.searchParams.append(key, value);
            });

            const response = await fetch(url.toString(), {
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json',
                }
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            if (data.success) {
                return data;
            }
        } catch (error) {
            console.error('[AdminDataManager] Error loading processing requests:', error);
            throw error;
        }
    }

    /**
     * Get current user profile
     */
    async getUserProfile() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/profile/`, {
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json',
                }
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            if (data.success) {
                return data.profile;
            }
        } catch (error) {
            console.error('[AdminDataManager] Error loading profile:', error);
            throw error;
        }
    }

    /**
     * Update user profile
     */
    async updateProfile(profileData) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/profile/update/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(profileData)
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            if (data.success) {
                this.showNotification(data.message, 'success');
                return data;
            }
        } catch (error) {
            console.error('[AdminDataManager] Error updating profile:', error);
            this.showNotification('Failed to update profile', 'error');
            throw error;
        }
    }

    /**
     * Change password
     */
    async changePassword(currentPassword, newPassword, confirmPassword) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/profile/change-password/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword,
                    confirm_password: confirmPassword
                })
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            if (data.success) {
                this.showNotification(data.message, 'success');
                return data;
            }
        } catch (error) {
            console.error('[AdminDataManager] Error changing password:', error);
            const errorMsg = error.message || 'Failed to change password';
            this.showNotification(errorMsg, 'error');
            throw error;
        }
    }

    /**
     * Upload profile photo
     */
    async uploadProfilePhoto(file) {
        try {
            const formData = new FormData();
            formData.append('photo', file);

            const response = await fetch(`${this.apiBaseUrl}/profile/upload-photo/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                },
                body: formData
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            if (data.success) {
                this.showNotification(data.message, 'success');
                return data;
            }
        } catch (error) {
            console.error('[AdminDataManager] Error uploading photo:', error);
            this.showNotification('Failed to upload photo', 'error');
            throw error;
        }
    }

    /**
     * Reassign processing request
     */
    async reassignRequest(loanId, assigneeType, assigneeId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/processing-requests/reassign/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loan_id: loanId,
                    assignee_type: assigneeType,
                    assignee_id: assigneeId
                })
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            if (data.success) {
                this.showNotification(data.message, 'success');
                return data;
            }
        } catch (error) {
            console.error('[AdminDataManager] Error reassigning request:', error);
            this.showNotification('Failed to reassign request', 'error');
            throw error;
        }
    }

    /**
     * Auto-refresh data
     */
    startAutoRefresh() {
        if (this.refreshInterval) return;
        this.refreshInterval = setInterval(() => {
            this.loadDashboardStats();
        }, this.updateInterval);
    }

    pauseAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    /**
     * Handle API errors
     */
    handleApiError(error) {
        this.retryCount++;
        if (this.retryCount <= this.maxRetries) {
            console.log(`[AdminDataManager] Retrying... (${this.retryCount}/${this.maxRetries})`);
            setTimeout(() => {
                this.loadDashboardStats();
            }, 5000 * this.retryCount); // Exponential backoff
        } else {
            console.error('[AdminDataManager] Max retries exceeded');
        }
    }

    /**
     * Show notification
     */
    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 16px 20px;
            background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 9999;
            animation: slideIn 0.3s ease;
            max-width: 400px;
        `;
        notification.textContent = message;

        document.body.appendChild(notification);

        // Auto-remove after 3 seconds
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    /**
     * Get CSRF token
     */
    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
               document.cookie.split(';')
                   .find(c => c.trim().startsWith('csrftoken='))
                   ?.split('=')[1] ||
               '';
    }

    /**
     * Load initial data
     */
    async loadInitialData() {
        try {
            await this.loadDashboardStats();
        } catch (error) {
            console.error('[AdminDataManager] Error loading initial data:', error);
        }
    }
}

// Initialize on page load
let adminDataManager;
document.addEventListener('DOMContentLoaded', () => {
    adminDataManager = new AdminDataManager();
});

// Add animation styles
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);
