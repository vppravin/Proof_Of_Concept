from io import BytesIO
from fpdf import FPDF
from google.cloud import storage
from google.cloud import bigquery
import datetime
import yfinance as yf
from vertexai.preview.generative_models import GenerativeModel, Part
import vertexai
import re
import logging
from dotenv import load_dotenv
import os
from fastmcp import FastMCP

# Load environment variables FIRST
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [360_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Initializing FastMCP server...")
mcp = FastMCP("360 Agent Tools")
logger.info("FastMCP server initialized")
api_key = os.getenv("GEMINI_API_KEY")
model = os.getenv("model")
project_id = os.getenv("PROJECT_ID")
bucket_name = os.getenv("BUCKET_NAME")
cloud_run_url = os.getenv("CLOUD_RUN_URL")
gcs_bucket = os.getenv("GCS_BUCKET")
input_pdf_blob = os.getenv("INPUT_PDF_BLOB")
output_txt_blob = os.getenv("OUTPUT_TXT_BLOB")
local_temp_pdf = os.getenv("LOCAL_TEMP_PDF")
local_output_txt = os.getenv("LOCAL_OUTPUT_TXT")
sdi_table = os.getenv("SDI_TABLE")
sma_table = os.getenv("SMA_TABLE")
checking_table = os.getenv("CHECKING_TABLE")
managed_table = os.getenv("MANAGED_TABLE")
savings_table = os.getenv("SAVINGS_TABLE")
funds_table = os.getenv("FUNDS_TABLE")

# Initialize Vertex AI
vertexai.init(project=project_id, location="us-central1")

client = bigquery.Client(project=project_id)

def split_insights(text):
    # Match segments starting with a capitalized title followed by a colon
    pattern = r'([A-Z][A-Za-z0-9 &()\-]{3,}):'
    matches = list(re.finditer(pattern, text))
    segments = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        segment = text[start:end].strip()
        segments.append(segment)
    return segments

def generate_pdf_report(results, details, bucket_name, file_path, file_name):
    class PDF(FPDF):
        def header(self):
            self.set_font("Helvetica", 'B', 14)
            self.set_text_color(0, 51, 102)
            self.cell(0, 10, "360° Financial Summary Report", ln=True, align='C')
            self.set_draw_color(0, 102, 204)
            self.line(10, 20, 200, 20)
            self.ln(10)
        def chapter_title(self, title):
            self.set_font("Helvetica", 'B', 12)
            self.set_text_color(0, 0, 102)
            self.cell(0, 10, f"{title}", ln=True)
            self.set_draw_color(0, 102, 204)
            self.set_line_width(0.5)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(5)
            self.set_text_color(0, 0, 0)
        def accept_page_break(self):
            return False  # Prevent splitting of tables or insights
    def sanitize_text(text):
        replacements = {
            '‘': "'", '’': "'",  # Curly single quotes → straight
            '“': '"', '”': '"',  # Curly double quotes → straight
            '–': '-', '—': '-',  # Dashes → hyphen
            '…': '...',          # Ellipsis
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text.replace("\n", " ").strip()
    pdf = PDF()
    pdf.add_page()
    # Lead Details
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 10, f"Client: {details.get('Lead Name')}", ln=True)
    pdf.set_font("Helvetica", '', 10)
    for label, value in details.items():
        pdf.cell(40, 8, f"{label}:", ln=0)
        pdf.cell(0, 8, f"{value}", ln=1)
    pdf.ln(5)
    for section_title, data in results.items():
        title_clean = section_title.replace("_", " ").title()
        if isinstance(data, list) and data and isinstance(data[0], dict):
            # Estimate row height
            row_height = 8
            header_height = 8
            padding_height = 5
            total_rows = len(data)
            estimated_table_height = header_height + total_rows * row_height + padding_height

            # If not enough space on current page, add new page
            if pdf.get_y() + estimated_table_height > pdf.h - 20:
                pdf.add_page()

            pdf.ln(3)
            pdf.chapter_title(title_clean.upper())
            headers = list(data[0].keys())
            pdf.set_font("Helvetica", 'B', 9)

            # Calculate column widths
            col_widths = [
                max(pdf.get_string_width(str(h).upper()), max(pdf.get_string_width(str(row[h])) for row in data)) + 6
                for h in headers
            ]
            total_width = sum(col_widths)
            x_start = (pdf.w - total_width) / 2
            pdf.set_x(x_start)

            # Header row
            pdf.set_fill_color(220, 230, 240)
            pdf.set_text_color(0, 0, 0)
            for i, h in enumerate(headers):
                pdf.cell(col_widths[i], 8, h.upper(), border=1, align='C', fill=True)
            pdf.ln()

            # Data rows
            fill = False
            pdf.set_font("Helvetica", '', 8)
            for row in data:
                pdf.set_x(x_start)
                pdf.set_fill_color(245, 245, 245) if fill else pdf.set_fill_color(255, 255, 255)
                for i, h in enumerate(headers):
                    pdf.cell(col_widths[i], 8, str(row[h]), border=1, fill=fill)
                pdf.ln()
                fill = not fill

            pdf.ln(5)    
        elif isinstance(data, str):
            insight_text = sanitize_text(data)
            # Split insights by double newline
            segments = split_insights(insight_text)
            # Strip whitespace
            segments = [s.strip() for s in segments]
            # print(segments)
            if not segments:
                # Estimate height
                pdf.set_font("Helvetica", '', 10)
                line_height = 6.5
                lines = pdf.multi_cell(0, line_height, insight_text, split_only=True)
                required_height = line_height * len(lines) + 6  # +6 for label
                if pdf.get_y() + required_height > pdf.h - 20:
                    pdf.add_page()
                # Label
                pdf.set_font("Helvetica", 'B', 9)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 6, "[Insights]", ln=True)
                pdf.ln(1)
                # Plain text (no fill)
                pdf.set_font("Helvetica", '', 10)
                pdf.set_text_color(30, 30, 30)
                pdf.multi_cell(0, 6.5, insight_text)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(4)
            else:
                # Label
                pdf.set_font("Helvetica", 'B', 9)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 6, "[Insights]", ln=True)
                pdf.ln(2)
                pdf.set_text_color(30, 30, 30)
                line_height = 6.5
                page_width = pdf.w - pdf.l_margin - pdf.r_margin
                for seg in segments:
                    if ":" in seg:
                        key, val = seg.split(":", 1)
                        key = key.strip() + ":"
                        val = val.strip()
                        # Print bold key on its own line
                        pdf.set_font("Helvetica", 'B', 10)
                        pdf.cell(0, line_height, key, ln=True)
                        # Print regular value below, wrapped, left aligned
                        pdf.set_font("Helvetica", '', 10)
                        pdf.multi_cell(0, line_height, val)
                        pdf.ln(1)
                    else:
                        # No colon — print normally
                        pdf.set_font("Helvetica", '', 10)
                        pdf.multi_cell(0, line_height, seg.strip())
                        pdf.alias_nb_pages
                    pdf.ln(1)               
        else:
            pdf.chapter_title(title_clean)
            pdf.set_font("Helvetica", '', 10)
            pdf.cell(0, 8, "No records found.", ln=True)
            pdf.ln(5)
    # Export PDF
    pdf_output = BytesIO()
    pdf.output(pdf_output)
    pdf_output.seek(0)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    blob.upload_from_file(pdf_output, content_type="application/pdf")
    return f"{cloud_run_url}/chart/{file_name}"

def agent_360_summary(name: str):
    results = {}
    client = bigquery.Client(project=project_id)

    details_query = f"""
        SELECT Lead_Name, Address, Phone, Email
        FROM {sdi_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
        LIMIT 1
    """
    res = client.query(details_query).result()
    result_det = [{"Lead Name": row.Lead_Name, "Address": row.Address, "Phone": row.Phone, "Email": row.Email} for row in res]
    customer_details = result_det[0]

    query1 = f"""
        SELECT Activity, SUM(CASE 
                WHEN Amount IS NOT NULL THEN Amount ELSE 0 END) AS Total_Amount
        FROM {sdi_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
        GROUP BY Activity
    """
    result1 = client.query(query1).result()
    activity_totals = [{"Activity": row.Activity, "Total_Amount": f"$ {row.Total_Amount:.2f}"} for row in result1 if row.Total_Amount!= 0.0]
    results['sdi_activity_totals'] = activity_totals
    
    sdi_query = f"""
        SELECT Date, Activity, Description, Quantity, UnitPrice, Commission, Amount, Balance FROM {sdi_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
    """
    sdi_rows = client.query(sdi_query).result()
    sdi_data = [{"Date": str(row.Date), "Activity": row.Activity, "Description": row.Description, "Quantity": row.Quantity, "UnitPrice": row.UnitPrice, "Commission": row.Commission, "Amount": row.Amount, "Balance": row.Balance} for row in sdi_rows]
    insight_model = GenerativeModel("gemini-2.5-flash")
    prompt = f"""
    This is the activity-wise summary totals: {results["sdi_activity_totals"]}
    Can you derive personalized insights on the customer's SDI account investment trends using the detailed transaction data below?
    Here is the detailed transaction data: {sdi_data}
    Please follow this format for each insight:
    - Start with a short title-style key phrase (e.g., "Key Phrase 1", "Key Phrase 2")
    - Add a colon `:` and then a short, clear explanation tailored to the data
    - Do not use bullet points or numbering
    - Use at least 1 and at most 3 such insights, each as a separate line
    - Keep the text crisp and professional (max 200 words total)
    - Use USD for currency if needed
    - Avoid generic statements; insights should reflect the data
    """
    response = insight_model.generate_content(prompt)
    results["sdi_activity_insight"] = response.text

    query2 = f"""
        SELECT * FROM (
        SELECT 'Highest_Purchased' AS Category, Description, SUM(CASE 
                WHEN Amount IS NOT NULL THEN Amount ELSE 0 END) AS Total_Amount
        FROM {sdi_table}
        WHERE (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
            AND lower(Activity) = 'purchase'
        GROUP BY Description
        ORDER BY Total_Amount DESC
        LIMIT 1
        )
        
        UNION ALL

        SELECT * FROM (
        SELECT 'Highest_Sold' AS Category, Description, SUM(CASE 
                WHEN Amount IS NOT NULL THEN Amount ELSE 0 END) AS Total_Amount
        FROM {sdi_table}
        WHERE (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
            AND lower(Activity) = 'sale'
        GROUP BY Description
        ORDER BY Total_Amount DESC
        LIMIT 1
        )
        
        UNION ALL

        SELECT * FROM (
        SELECT 'Highest_Dividend_Paying' AS Category, Description, SUM(CASE 
                WHEN Amount IS NOT NULL THEN Amount ELSE 0 END) AS Total_Amount
        FROM {sdi_table}
        WHERE (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
            AND lower(Activity) = 'dividend'
        GROUP BY Description
        ORDER BY Total_Amount DESC
        LIMIT 1
        )
    """
    result2 = client.query(query2).result()
    top_stocks = [{"Category": row.Category, "Description": row.Description, "Total_Amount": f"$ {row.Total_Amount:.2f}"} for row in result2]
    results['top_stocks_summary'] = top_stocks
    
    prompt = f"""
    This is the top stocks summary: {results["top_stocks_summary"]}
    Can you derive insightful observations about the customer’s stock transactions (purchases, sales, holdings, etc.) using the detailed data below?
    Here is the full transaction data: {sdi_data}
    Please format each insight as:
    - Start with a short title-style key phrase (e.g., "Key Phrase 1", "Key Phrase 2")
    - Add a colon `:` and then a short, clear explanation tailored to the data
    - Do not use bullet points or numbering
    - Use at least 1, at most 3 such insights, each as a separate line
    - Keep the text crisp and professional (max 200 words total)
    - Use USD for currency if needed
    - Avoid generic statements; insights should reflect the data
    """
    response = insight_model.generate_content(prompt)
    results["top_stock_insight"] = response.text    
    
    stock_query = f"""
    SELECT * FROM (
        SELECT 'Top_Purchases' AS Category, Description, SUM(CASE 
                WHEN Amount IS NOT NULL THEN Amount ELSE 0 END) AS Total_Amount
        FROM {sdi_table}
        WHERE (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
            AND lower(Activity) = 'purchase'
        GROUP BY Description
        ORDER BY Total_Amount DESC
        LIMIT 5
        )
    """
    stock_results = list(client.query(stock_query).result())
    purchased_stocks =  [{"Description": row.Description, "Total_Amount": f"$ {row.Total_Amount:.2f}"} for row in stock_results]
    results["stocks_purchased"] = purchased_stocks
    
    purchased_companies = []
    for row in stock_results:
        purchased_companies.append(str(row.Description))
    # companies = [c.strip() for c in re.split(r",|\band\b", company, flags=re.IGNORECASE) if c.strip()]
    days = 10
    stock_trends = []
    for comp in purchased_companies:
        try:
            stock = yf.Ticker(comp)
            end = datetime.datetime.now()
            start = end - datetime.timedelta(days=days + 5)
            hist = stock.history(start=start.strftime('%Y-%m-%d'), end=end.strftime('%Y-%m-%d'))
            closing = hist["Close"].dropna().tail(days).tolist()
            if not closing or len(closing) < 2:
                stock_trends.append(f"Not enough data for {comp}")
                continue
            trend = "rising" if closing[-1] > closing[0] else "falling"
            price_str = ", ".join([f"${p:.2f}" for p in closing])
            stock_trends.append(f"{comp.upper()} - {trend} over {len(closing)} days:\n{price_str}")
        except Exception as e:
            stock_trends.append(f"Error for {comp}: {str(e)}")
    
    prompt = f"""
    This is the top stocks purchased: {results["stocks_purchased"]}
    Can you provide tailored insights into the customer's recent stock purchases using the detailed stock trend data below?
    Here is the stock trend for top stocks purchased: {stock_trends}
    Please format each insight as:
    - Start with a short title-style key phrase (e.g., "Key Phrase 1", "Key Phrase 2")
    - Add a colon `:` and then a short, clear explanation tailored to the data
    - Do not use bullet points or numbering
    - Use at least 1, at most 3 such insights, each as a separate line
    - Keep the text crisp and professional (max 200 words total)
    - Use USD for currency if needed
    - Avoid generic statements; insights should reflect the data
    """
    response = insight_model.generate_content(prompt)
    results["stocks_puchased_insight"] = response.text 
    
    query3 = f"""
        SELECT
            CASE
            WHEN LOWER(Description) LIKE 'buy:%' THEN 'Investment Purchase'
            WHEN LOWER(Description) LIKE 'sell:%' THEN 'Investment Sale'
            WHEN LOWER(Activity_Type) IN ('dividend', 'interest') OR LOWER(Description) LIKE '%coupon%' THEN 'Investment Income'
            WHEN LOWER(Activity_Type) LIKE '%fee%' OR LOWER(Description) LIKE '%fee%' THEN 'Fees'
            WHEN LOWER(Activity_Type) LIKE '%tax%' THEN 'Taxes'
            WHEN LOWER(Activity_Type) = 'deposit' THEN 'Deposit'
            WHEN LOWER(Activity_Type) LIKE '%fx%' THEN 'FX Gain/Loss'
            WHEN LOWER(Activity_Type) = 'withdrawal' THEN 'Withdrawal'
            ELSE 'Others'
            END AS Group_Type,
            SUM(CASE 
                WHEN Amount IS NOT NULL THEN Amount ELSE 0 END) AS Total_Amount
        FROM {sma_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
        GROUP BY Group_Type
    """
    result3 = client.query(query3).result()
    results["sma_activity_totals"] = [{"Group_Type": row["Group_Type"], "Total_Amount": f"$ {row.Total_Amount:.2f}"} for row in result3]
    
    sma_query = f"""
        SELECT Date, Activity_Type, Description, Quantity, UnitPrice, Amount, Balance FROM {sma_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
    """
    sma_rows = client.query(sma_query).result()
    sma_data = [{"Date": str(row.Date), "Activity": row.Activity_Type, "Description": row.Description, "Quantity": row.Quantity, "UnitPrice": row.UnitPrice, "Amount": row.Amount, "Balance": row.Balance} for row in sma_rows]
    prompt = f"""
    This is the activity-wise summary totals: {results["sma_activity_totals"]}
    Can you provide tailored insights into the customer's SMA (Separately Managed Account) activity using the detailed transaction data below?
    Here is the whole detailed transaction data: {sma_data}
    Please format each insight as:
    - Start with a short title-style key phrase (e.g., "Key Phrase 1", "Key Phrase 2")
    - Add a colon `:` and then a short, clear explanation tailored to the data
    - Do not use bullet points or numbering
    - Use at least 1, at most 3 such insights, each as a separate line
    - Keep the text crisp and professional (max 200 words total)
    - Use USD for currency if needed
    - Avoid generic statements; insights should reflect the data
    """
    response = insight_model.generate_content(prompt)
    results["sma_activity_insight"] = response.text 
    
    subqueries = []
    subqueries.append(f"""
        SELECT Lead_Name, SUM(CASE 
                WHEN Amount IS NOT NULL THEN Amount ELSE 0 END) AS amt
        FROM {sma_table}
        WHERE LOWER(Description) LIKE '%retirement plan contribution%'
        AND (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
        GROUP BY Lead_Name
    """)
    subqueries.append(f"""
        SELECT Lead_Name, SUM(CASE 
                WHEN Debit IS NOT NULL THEN Debit ELSE 0 END) AS amt
        FROM {checking_table}
        WHERE LOWER(Description) LIKE '%goal contribution%'
        AND (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
        GROUP BY Lead_Name
    """)
    subqueries.append(f"""
        SELECT Lead_Name, SUM(CASE 
                WHEN Credit IS NOT NULL THEN Credit ELSE 0 END) AS amt
        FROM {savings_table}
        WHERE LOWER(Description) LIKE '%home goal contribution%'
        AND (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
        GROUP BY Lead_Name
    """)
    subqueries.append(f"""
        SELECT Lead_Name, SUM(CASE 
                WHEN Credit IS NOT NULL THEN Credit ELSE 0 END) AS amt
        FROM {managed_table}
        WHERE LOWER(Description) LIKE '%retirement goal contribution%'
        AND (lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}'))
        GROUP BY Lead_Name
    """)
    union_query = " UNION ALL ".join(subqueries)
    full_query = f"""
        SELECT Lead_Name, SUM(amt) AS Actual_Investment
        FROM ({union_query})
        GROUP BY Lead_Name
    """
    result4 = client.query(full_query).result()
    results["actual_vs_target_investment"] = [{"Target": "$ 500000.00", "Actual": f"$ {row.Actual_Investment:.2f}", "Difference": f"$ {500000.00 - row.Actual_Investment:.2f}", "Status": "below target" if row.Actual_Investment < 500000.00 else "above target"} for row in result4]
    
    query10 = f"""
        SELECT Date, Description, Credit
        FROM {checking_table}
        WHERE (LOWER(Lead_Name) = LOWER('{name}') OR LOWER(Lead_ID) = LOWER('{name}'))
        AND LOWER(Description) LIKE '%payroll bonus%'
    """
    bonus_rows = client.query(query10).result()
    payroll_bonuses = [{"Date": str(row.Date), "Description": row.Description, "Credit": f"$ {row.Credit:.2f}"} for row in bonus_rows]
    results["payroll_bonus_details"] = payroll_bonuses
    
    prompt = f"""
    You are a financial advisor.
    This is the actual vs. target investment comparison data: {results["actual_vs_target_investment"]}
    This is the user's payroll bonus details: {results["payroll_bonus_details"]}
    Generate 1–2 personalized and data-driven financial recommendations based on the information above.
    Use the following format:
    - Start with a short title-style key phrase (e.g., "Key Phrase 1", "Key Phrase 2")
    - Add a colon `:` and then a short, clear explanation tailored to the data
    - Do not use bullet points or numbering
    - Keep the text crisp and professional (max 200 words total)
    - Use USD for currency if needed
    - Avoid generic statements; insights should reflect the data
    - If the user is already on track, simply state: "All targets are being met. No changes recommended."
    """
    response = insight_model.generate_content(prompt)
    results["financial_recommendations"] = response.text
    
    query6 = f"""
        SELECT
        -- Home Expenses
        SUM(CASE 
                WHEN Debit IS NOT NULL AND Description NOT IN (
                    'Transfer-SMA- Goal Contribution',
                    'Transfer-Managed- Goal Contribution',
                    'Transfer-Savings- Goal Contribution'
                )
                THEN Debit ELSE 0 END) AS Home_Expenses,

        -- Home Goal Investments
        SUM(CASE 
                WHEN Debit IS NOT NULL AND Description IN (
                    'Transfer-SMA- Goal Contribution',
                    'Transfer-Managed- Goal Contribution',
                    'Transfer-Savings- Goal Contribution'
                )
                THEN Debit ELSE 0 END) AS Home_Goal_Investments,

        -- Credit_Inflow
        SUM(CASE 
                WHEN Credit IS NOT NULL THEN Credit ELSE 0 END) AS Credit_Inflow
        FROM {checking_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
    """
    result6 = client.query(query6).result()
    summary = [{"Home_Expenses": f"$ {row.Home_Expenses:.2f}", "Home_Goal_Investments": f"$ {row.Home_Goal_Investments:.2f}", "Credit_Inflow": f"$ {row.Credit_Inflow:.2f}"} for row in result6]
    results["Checking_Summary"] = summary
    
    checking_query = f"""
        SELECT Date, Description, Debit, Credit, Balance FROM {checking_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
    """
    checking_rows = client.query(checking_query).result()
    checking_data = [{"Date": str(row.Date), "Description": row.Description, "Debit": row.Debit, "Credit": row.Credit, "Balance": row.Balance} for row in checking_rows]
    prompt = f"""
    This is the activity-wise summary totals: {results["Checking_Summary"]}
    Can you provide insight on the customer's Checking Account using the detailed data below?
    Here is the whole detailed transaction data: {checking_data}
    Use the following format:
    - Start with a short title-style key phrase (e.g., "Key Phrase 1", "Key Phrase 2")
    - Add a colon `:` and then a short, clear explanation tailored to the data
    - Do not use bullet points or numbering
    - Use at least 1, at most 3 such insights, each as a separate line
    - Keep the text crisp and professional (max 200 words total)
    - Use USD for currency if needed
    - Avoid generic statements; insights should reflect the data
    """
    response = insight_model.generate_content(prompt)
    results["checking_account_insight"] = response.text 

    query7 = f"""
        SELECT
            fund_name,
            total_units,
            current_nav,
            current_value,
            total_invested,
            (current_value - total_invested) AS absolute_return,
            SAFE_DIVIDE((current_value - total_invested), total_invested) * 100 AS return_percentage
        FROM {funds_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
    """
    results7 = client.query(query7).result()
    funds_summary = []
    for row in results7:
        funds_summary.append({
            "Fund": row["fund_name"],
            "Units": row["total_units"],
            "NAV": row["current_nav"],
            "Current_Value": f"$ {row['current_value']:.2f}",
            "Invested": f"$ {row['total_invested']:.2f}",
            "Return": f"$ {row['absolute_return']:.2f}",
            "Return_%": f"{row['return_percentage']:.2f} %"
        })
    results["Fund_Summary"] = funds_summary
    
    funds_query = f"""
        SELECT fund_name, fund_type, investment_mode, total_units, current_nav, current_value, total_invested FROM {funds_table}
        WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
    """
    # WHERE lower(Lead_Name) = lower('{name}') OR lower(Lead_ID) = lower('{name}')
    funds_rows = client.query(funds_query).result()
    funds_data = [{"fund_name": row.fund_name, "fund_type": row.fund_type, "investment_mode": row.investment_mode, "total_units": row.total_units, "current_nav": row.current_nav, "current_value":row.current_value, "total_invested":row.total_invested} for row in funds_rows]
    prompt = f"""
    This is the fund summary: {results["Fund_Summary"]}
    Can you provide insight on the customer's Funds Account using the detailed data below?
    Here is the whole detailed transaction data: {funds_data}
    Use the following format:
    - Start with a short title-style key phrase (e.g., "Key Phrase 1", "Key Phrase 2")
    - Add a colon `:` and then a short, clear explanation tailored to the data
    - Do not use bullet points or numbering
    - Use at least 1, at most 3 such insights, each as a separate line
    - Keep the text crisp and professional (max 200 words total)
    - Use USD for currency if needed
    - Avoid generic statements; insights should reflect the data
    """
    response = insight_model.generate_content(prompt)
    results["funds_account_insight"] = response.text
    
    return results, customer_details

@mcp.tool
def agent_360_summary_with_pdf(name: str):
    logger.info(f"Tool invoked: agent_360_summary_with_pdf for {name}")
    result, details = agent_360_summary(name)
    name = name.upper()
    name = name.replace(" ", "_")
    url = generate_pdf_report(result, details, bucket_name, f"reports/360_summary_{name}.pdf", f"360_summary_{name}.pdf")
    logger.info(f"PDF report generated: {url}")
    return {"PDF Report URL": url}


# SSE + Starlette app config
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from mcp.server.sse import SseServerTransport
import uvicorn

sse = SseServerTransport("/sse/messages")

async def handle_sse(request: Request):
    logger.info(f"SSE connection request received from {request.client.host}")
    _server = mcp._mcp_server
    async with sse.connect_sse(
        request.scope,
        request.receive,
        request._send,
    ) as (reader, writer):
        logger.info("SSE connection established, running MCP server...")
        await _server.run(reader, writer, _server.create_initialization_options())
        logger.info("MCP server session completed")

async def health_check(request: Request):
    logger.debug("Health check requested")
    return JSONResponse({"status": "healthy", "service": "360 Agent MCP Server"})

async def serve_chart(request: Request):
    """Serve PDF files from GCS bucket"""
    filename = request.path_params['filename']
    logger.info(f"Serving chart/PDF: {filename}")
    
    try:
        storage_client = storage.Client(project=project_id)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(f"reports/{filename}")
        
        if not blob.exists():
            logger.error(f"File not found: {filename}")
            return JSONResponse({"error": "File not found"}, status_code=404)
        
        pdf_data = blob.download_as_bytes()
        logger.info(f"Successfully served {filename}, size: {len(pdf_data)} bytes")
        
        return Response(
            pdf_data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'}
        )
    except Exception as e:
        logger.error(f"Error serving PDF {filename}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

app = Starlette(
    debug=False,
    routes=[
        Route("/", endpoint=health_check),
        Route("/health", endpoint=health_check),
        Route("/sse", endpoint=handle_sse),
        Route("/chart/{filename}", endpoint=serve_chart),  # PDF serving endpoint
        Mount("/sse/", app=sse.handle_post_message),
    ],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info("🚀 Starting 360 Agent MCP Server...")
    logger.info(f"Server will listen on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
