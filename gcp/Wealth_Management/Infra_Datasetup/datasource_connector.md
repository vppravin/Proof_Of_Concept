# Data Source Connectors

## Workspace Sources

### Google Drive
- Access and retrieve documents, spreadsheets, and files
- Integration for wealth management reports and client documents

### Google Gmail
- Email communication and notifications
- Client correspondence tracking

### Google Calendar
- Schedule management and event tracking
- Actions:
  - Create Calendar event
  - Update Calendar event

## Cloud Sources

### Cloud Storage (Unstructured Data)
- Store PDFs, documents, and reports
- Buckets:
  - `wealth-fund-documents-146646146609/` - Fund documents
  - `wealth-360-reports-146646146609/` - Generated reports

### BigQuery (Structured Data)
- Wealth management transactional data
- Tables:
  - SMA (Structured Managed Accounts)
  - SDI (Self-Directed Investments)
  - Checking
  - Savings
  - Managed
  - Funds

#### Prerequisites
1. **Column Naming Convention**: Use snake_case (e.g., `Lead_Name`, `Activity_Type`, `Investment_Amount`)
2. **Null Value Handling**: Replace all NULL values with 0.0 for numeric columns

## Third-Party Sources

### ServiceNow
- Incident and ticket management
- Actions:
  - Create an Incident
  - Update an Incident

#### Prerequisites
1. Navigate to ServiceNow instance: **System OAuth > Application Registry**
2. Create an OAuth API endpoint for external clients
3. Configure OAuth credentials:
   - Client ID
   - Client Secret
   - Token URL
4. Set required scopes for incident management
