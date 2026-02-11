# Loans Table - Quick Reference & Testing Guide

## Quick Start

### Accessing the All Loans Table
1. Login as Admin
2. Navigate to Admin Dashboard
3. Click "All Loans" from sidebar

### Key Interface Elements

#### 1. Search Bar
- Real-time search functionality
- Search by borrower name, email, or phone
- Results filter instantly as you type

#### 2. Loan Table
- Displays all loans with key information
- Click "View" to see full details
- Click "Edit" to manage application
- Click "Delete" to remove loan

#### 3. Status Indicators
- **New Entry** (Blue) - Recently added
- **Waiting** (Yellow) - Pending processing
- **Follow-up** (Green) - Needs attention
- **Approved** (Green) - Ready
- **Rejected** (Red) - Declined
- **Disbursed** (Green) - Completed

## Detailed Workflow

### Viewing Loan Details

**Steps:**
1. Find loan in table
2. Click "View" button (blue)
3. Modal opens showing 7 sections of information
4. Scroll through to see all details
5. Close with X button or Escape key

**Visible Information:**
- Personal details (Name, Contact, Address)
- Occupation & Income
- Existing loans
- Loan request details
- References
- Financial & Bank details
- Attached documents

### Rejecting a Loan

**Steps:**
1. Find loan in table
2. Click "View" button to see details (optional)
3. Click "Edit" button (teal)
4. Select "Reject Application" option
5. Enter detailed rejection reason (required)
6. Click "Submit"
7. See success notification
8. Page auto-reloads with updated status

**Rejection Reasons (Examples):**
- Credit score too low
- Existing EMI obligations excessive
- Insufficient income verification
- Missing required documents
- Applicant doesn't meet criteria

### Disbursing a Loan

**Steps:**
1. Find loan in table
2. Click "View" button to see details (optional)
3. Click "Edit" button (teal)
4. Select "Mark as Disbursed" option
5. (Optional) Add disbursement notes
6. Click "Submit"
7. See success notification
8. Page auto-reloads with updated status

**Disbursement Notes (Examples):**
- Transferred to account ending in 1234
- Reference: TRF123456789
- Bank verified on 2024-02-10
- All documents verified

### Deleting a Loan

**Steps:**
1. Find loan in table
2. Click "View" button to see details (optional)
3. Click "Delete" button (red)
4. Confirm deletion in prompt
5. See success notification
6. Loan removed from table

**Note:** Cannot delete loans marked as "Disbursed"

## Testing Scenarios

### Test 1: View Details Modal
- [ ] Select a loan from table
- [ ] Click "View" button
- [ ] Modal appears smoothly
- [ ] All 7 sections display
- [ ] Scroll works in modal
- [ ] X button closes modal
- [ ] Outside click closes modal
- [ ] Escape key closes modal

### Test 2: Search Functionality
- [ ] Type borrower name in search
- [ ] Results filter in real-time
- [ ] Type email address
- [ ] Results filter correctly
- [ ] Type phone number
- [ ] Results show matching entries
- [ ] Clear search shows all loans
- [ ] Case-insensitive search works

### Test 3: Reject Functionality
- [ ] Select "Reject Application"
- [ ] Reason field appears
- [ ] Try submit without reason (should fail)
- [ ] Add rejection reason
- [ ] Click submit
- [ ] Success toast appears
- [ ] Status updates to "Rejected"
- [ ] Color changes to red

### Test 4: Disburse Functionality
- [ ] Select "Mark as Disbursed"
- [ ] Notes field appears (optional)
- [ ] Add optional notes
- [ ] Click submit
- [ ] Success toast appears
- [ ] Status updates to "Disbursed"
- [ ] Color changes to green
- [ ] Loan can no longer be deleted

### Test 5: Delete Functionality
- [ ] Try to delete a disbursed loan (should fail)
- [ ] Select a non-disbursed loan
- [ ] Click delete button
- [ ] Confirmation appears
- [ ] Confirm deletion
- [ ] Success toast appears
- [ ] Loan removed from table

### Test 6: Responsive Design
- [ ] Resize to mobile (320px)
- [ ] Table scrolls horizontally
- [ ] Buttons remain clickable
- [ ] Modal fits on screen
- [ ] Sections stack vertically
- [ ] Resize to tablet (768px)
- [ ] Resize to desktop (1920px)

### Test 7: API Endpoints
- [ ] GET `/api/loan/1/details/` returns JSON
- [ ] POST `/api/loan/1/reject/` updates status
- [ ] POST `/api/loan/1/disburse/` updates status
- [ ] DELETE `/api/loan/1/delete/` removes loan
- [ ] Unauthenticated access denied
- [ ] Non-admin access denied

## Troubleshooting

### Issue: Modal doesn't open
**Solution:**
- Check browser console for errors
- Verify loan ID is valid
- Check if API endpoint is working
- Try page refresh

### Issue: Search not working
**Solution:**
- Clear search box
- Type slowly to ensure input registers
- Check if data loaded correctly
- Try different search term

### Issue: Submit button doesn't work
**Solution:**
- Fill all required fields (reason for reject)
- Check browser console for errors
- Verify CSRF token is valid
- Try page refresh

### Issue: Status doesn't update
**Solution:**
- Wait for 2-second auto-reload
- Manually refresh page
- Check backend logs for errors
- Verify database connection

### Issue: Modals are overlapping
**Solution:**
- Close modals properly with X button
- Press Escape key
- Refresh page
- Check z-index in CSS

## Performance Tips

### For Admins:
- Search narrows results before opening modals
- Details modal loads only when opened
- Use Firefox/Chrome for best performance
- Close modals when done to free memory

### For Developers:
- API queries use select_related for optimization
- Prefetch related documents for speed
- Consider pagination for large datasets
- Monitor API response times

## Keyboard Shortcuts

- **Escape** - Close current modal
- **Enter** - Submit form (if focused on submit)
- **Tab** - Navigate through fields
- **Ctrl+F** - Browser find function

## Browser Compatibility

✓ Chrome 90+
✓ Firefox 88+
✓ Safari 14+
✓ Edge 90+

## Data Fields Reference

### Personal Information
- Full Name (required)
- Mobile Number (required)
- Alternate Mobile (optional)
- Email ID (required)
- Father's Name (required)
- Mother's Name (required)
- Date of Birth (required)
- Gender (required)
- Marital Status (optional)

### Address Information
- Permanent Address (breakdown: Street, City, PIN)
- Present Address (breakdown: Street, City, PIN)
- Same as Permanent option available

### Loan Details
- Loan Type (Personal, Home, Business, etc.)
- Loan Amount
- Loan Tenure (months)
- EMI Amount
- Interest Rate

### Financial Details
- CIBIL Score (0-900)
- Aadhar Number (12 digits)
- PAN Number (format: AAAAA0000A)

### Bank Details
- Bank Name
- Account Number
- Branch/IFSC

## Common Questions

**Q: Can I undo a rejection?**
A: No, rejected loans cannot be reverted. Contact admin to create new application.

**Q: Can I edit loan details?**
A: Currently, only status changes (Reject/Disburse). For other edits, contact developer.

**Q: What happens when I disburse?**
A: Loan status changes to "Disbursed" and cannot be deleted or modified.

**Q: How are documents downloaded?**
A: Click on document name/link in documents section to download.

**Q: Who can see details?**
A: Only authenticated admins can access loan details.

**Q: Is there an audit trail?**
A: Yes, all status changes are recorded with timestamp and admin name.

**Q: Can multiple admins edit simultaneously?**
A: Last edit wins. No real-time locking implemented.

## Success Indicators

✓ Green success toast notification appears
✓ Status badge changes color
✓ Table refreshes automatically
✓ Loan appears/disappears as appropriate
✓ Page shows updated information

## Next Steps

After implementing:

1. **Train Team**
   - Show admins the new interface
   - Practice with test loans
   - Review approval process

2. **Monitor Performance**
   - Check API response times
   - Monitor error rates
   - Optimize if needed

3. **Gather Feedback**
   - Ask admins what works well
   - Identify pain points
   - Plan improvements

4. **Plan Enhancements**
   - Bulk actions
   - Advanced filters
   - Export functionality
   - Real-time WebSocket updates

## Support & Issues

**For Backend Issues:**
- Check server logs
- Verify database connectivity
- Review API responses in browser dev tools

**For Frontend Issues:**
- Check browser console
- Clear cache and cookies
- Try different browser
- Verify JavaScript is enabled

**For Database Issues:**
- Verify models have required fields
- Check database permissions
- Review migration status
- Backup before major changes

**Contact:**
- Developer: [Contact info]
- Backup Admin: [Contact info]
- Support Ticket: [System]
