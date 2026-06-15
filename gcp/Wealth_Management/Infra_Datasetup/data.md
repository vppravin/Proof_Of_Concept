# Data Setup - BigQuery and Cloud Storage

## 1. BigQuery Dataset Creation

### Create Wealth_Management Dataset
```bash
# Create dataset
bq mk -d \
  --location=us-central1 \
  --description="Wealth Management data for multi-agent system" \
  gbu-demo-playground:Wealth_Management

# Verify
bq ls
```

## 2. BigQuery Tables

### Load Data from CSV with Auto-detected Schema

```bash
# SMA data
bq load \
  --source_format=CSV \
  --autodetect \
  --skip_leading_rows=1 \
  Wealth_Management.SMA \
  gs://your-bucket/data/sma.csv

# SDI data
bq load \
  --source_format=CSV \
  --autodetect \
  --skip_leading_rows=1 \
  Wealth_Management.SDI \
  gs://your-bucket/data/sdi.csv

# Checking data
bq load \
  --source_format=CSV \
  --autodetect \
  --skip_leading_rows=1 \
  Wealth_Management.Checking \
  gs://your-bucket/data/checking.csv

# Savings data
bq load \
  --source_format=CSV \
  --autodetect \
  --skip_leading_rows=1 \
  Wealth_Management.Savings \
  gs://your-bucket/data/savings.csv

# Managed data
bq load \
  --source_format=CSV \
  --autodetect \
  --skip_leading_rows=1 \
  Wealth_Management.Managed \
  gs://your-bucket/data/managed.csv

# Fund_Portfolio data
bq load \
  --source_format=CSV \
  --autodetect \
  --skip_leading_rows=1 \
  Wealth_Management.Fund_Portfolio \
  gs://your-bucket/data/fund_portfolio.csv
```

### Insert Sample Data via SQL (Alternative)
```sql
-- Sample SMA data
INSERT INTO `gbu-demo-playground.Wealth_Management.SMA` 
(Lead_Name, Date, Activity_Type, Description, Amount, Balance)
VALUES
('Peter Griffin', '2024-01-15', 'Deposit', 'Initial Investment', 50000.00, 50000.00),
('Peter Griffin', '2024-02-01', 'Buy', 'Buy: AAPL 100 shares', -15000.00, 35000.00),
('Peter Griffin', '2024-03-01', 'Dividend', 'Dividend from AAPL', 500.00, 35500.00);

-- Sample SDI data
INSERT INTO `gbu-demo-playground.Wealth_Management.SDI`
(Lead_Name, Date, Activity_Type, Company, Quantity, Price, Amount, Balance)
VALUES
('Peter Griffin', '2024-01-10', 'Purchase', 'GOOGL', 50, 140.00, 7000.00, 43000.00),
('Peter Griffin', '2024-02-15', 'Sale', 'MSFT', 30, 380.00, 11400.00, 54400.00),
('Peter Griffin', '2024-03-20', 'Dividend', 'AAPL', 0, 0.00, 250.00, 54650.00);
```

### Verify Tables
```bash
# List tables
bq ls Wealth_Management

# Check row counts
bq query --use_legacy_sql=false \
  'SELECT 
    (SELECT COUNT(*) FROM `gbu-demo-playground.Wealth_Management.SMA`) as SMA_rows,
    (SELECT COUNT(*) FROM `gbu-demo-playground.Wealth_Management.SDI`) as SDI_rows,
    (SELECT COUNT(*) FROM `gbu-demo-playground.Wealth_Management.Checking`) as Checking_rows'
```

## 3. Cloud Storage Buckets

### Create Buckets

#### Fund Documents Bucket
```bash
# Create bucket for fund PDFs
gsutil mb -l us-central1 gs://wealth-fund-documents-146646146609/

# Set lifecycle (optional - delete old files after 365 days)
cat > lifecycle.json << EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 365}
      }
    ]
  }
}
EOF

gsutil lifecycle set lifecycle.json gs://wealth-fund-documents-146646146609/
```

#### 360 Reports Bucket
```bash
# Create bucket for generated PDF reports
gsutil mb -l us-central1 gs://wealth-360-reports-146646146609/

# Make bucket publicly readable (for report URLs)
gsutil iam ch allUsers:objectViewer gs://wealth-360-reports-146646146609/
```

### Upload Fund Documents
```bash
# Upload fund PDFs
gsutil -m cp fund_documents/*.pdf gs://wealth-fund-documents-146646146609/

# Verify
gsutil ls gs://wealth-fund-documents-146646146609/
```

### Set Bucket Permissions
```bash
PROJECT_NUMBER="146646146609"
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Grant read access to fund documents
gsutil iam ch serviceAccount:${SERVICE_ACCOUNT}:objectViewer \
  gs://wealth-fund-documents-146646146609/

# Grant write access to 360 reports
gsutil iam ch serviceAccount:${SERVICE_ACCOUNT}:objectCreator \
  gs://wealth-360-reports-146646146609/
```

## 4. BigQuery Views (Optional)

Create views for common queries:

```sql
-- Lead Summary View
CREATE OR REPLACE VIEW `gbu-demo-playground.Wealth_Management.Lead_Summary` AS
SELECT 
  s.Lead_Name,
  SUM(s.Amount) as Total_SMA_Activity,
  SUM(sd.Amount) as Total_SDI_Activity,
  SUM(c.Credit - c.Debit) as Net_Checking,
  COUNT(DISTINCT f.Fund_Name) as Funds_Count
FROM `gbu-demo-playground.Wealth_Management.SMA` s
LEFT JOIN `gbu-demo-playground.Wealth_Management.SDI` sd ON s.Lead_Name = sd.Lead_Name
LEFT JOIN `gbu-demo-playground.Wealth_Management.Checking` c ON s.Lead_Name = c.Lead_Name
LEFT JOIN `gbu-demo-playground.Wealth_Management.Fund_Portfolio` f ON s.Lead_Name = f.Lead_Name
GROUP BY s.Lead_Name;
```

## 5. Data Validation

### Run Validation Queries
```bash
# Check for NULL values
bq query --use_legacy_sql=false \
  'SELECT 
    COUNT(*) as total_rows,
    COUNTIF(Lead_Name IS NULL) as null_lead_names,
    COUNTIF(Date IS NULL) as null_dates,
    COUNTIF(Amount IS NULL) as null_amounts
  FROM `gbu-demo-playground.Wealth_Management.SMA`'

# Check date ranges
bq query --use_legacy_sql=false \
  'SELECT 
    MIN(Date) as earliest_date,
    MAX(Date) as latest_date,
    COUNT(DISTINCT Lead_Name) as unique_leads
  FROM `gbu-demo-playground.Wealth_Management.SMA`'

# Check for duplicate records
bq query --use_legacy_sql=false \
  'SELECT 
    Lead_Name, Date, Description, COUNT(*) as count
  FROM `gbu-demo-playground.Wealth_Management.SMA`
  GROUP BY Lead_Name, Date, Description
  HAVING count > 1'
```

## 6. Sample Data Export

Export sample data for testing:

```bash
# Export SMA data
bq extract \
  --destination_format=CSV \
  Wealth_Management.SMA \
  gs://wealth-fund-documents-146646146609/exports/sma_export.csv

# Export SDI data
bq extract \
  --destination_format=CSV \
  Wealth_Management.SDI \
  gs://wealth-fund-documents-146646146609/exports/sdi_export.csv
```

## 7. Backup Configuration

### Automated Backups
```bash
# Create backup dataset
bq mk -d Wealth_Management_Backup

# Schedule backup (using Cloud Scheduler + Cloud Functions)
# See: https://cloud.google.com/bigquery/docs/scheduling-queries
```

## 8. Data Access Verification

Test data access with service account:

```python
# test_data_access.py
from google.cloud import bigquery
from google.cloud import storage

def test_bigquery():
    client = bigquery.Client(project="gbu-demo-playground")
    query = "SELECT COUNT(*) as count FROM `gbu-demo-playground.Wealth_Management.SMA`"
    result = client.query(query).result()
    for row in result:
        print(f"SMA rows: {row.count}")

def test_storage():
    client = storage.Client(project="gbu-demo-playground")
    bucket = client.bucket("wealth-fund-documents-146646146609")
    blobs = list(bucket.list_blobs(max_results=5))
    print(f"Found {len(blobs)} files in bucket")

if __name__ == "__main__":
    test_bigquery()
    test_storage()
```

Run test:
```bash
python test_data_access.py
```

## Next Steps

Proceed to **03-MCP-DEPLOYMENT.md** to deploy MCP servers.
