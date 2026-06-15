from io import BytesIO
from fpdf import FPDF
import datetime
import yfinance as yf
import re
import logging
import pyodbc
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from azure.storage.blob import BlobServiceClient, ContentSettings
from openai import AzureOpenAI
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
import uvicorn

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [360_MCP_SERVER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
BLOB_CONTAINER = os.getenv("BLOB_CONTAINER", "360-reports")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://agent-360-mcp.livelybay-96634f40.eastus2.azurecontainerapps.io")

openai_client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-15-preview"
)
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "wm-gpt4o")

logger.info("Initializing FastMCP server...")
mcp = FastMCP("360 Agent Tools")
logger.info("FastMCP server initialized")


def get_conn():
    return pyodbc.connect(AZURE_SQL_CONNECTION_STRING)


def get_insight(prompt: str) -> str:
    response = openai_client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400
    )
    return response.choices[0].message.content


def split_insights(text):
    pattern = r'([A-Z][A-Za-z0-9 &()\-]{3,}):'
    matches = list(re.finditer(pattern, text))
    segments = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        segments.append(text[start:end].strip())
    return segments


def generate_pdf_report(results, details, blob_container, file_path, file_name):
    class PDF(FPDF):
        def header(self):
            self.set_font("Helvetica", 'B', 14)
            self.set_text_color(0, 51, 102)
            self.cell(0, 10, "360 Financial Summary Report", ln=True, align='C')
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
            return False

    def sanitize(text):
        for old, new in [(''', "'"), (''', "'"), ('"', '"'), ('"', '"'), ('–', '-'), ('—', '-'), ('…', '...')]:
            text = text.replace(old, new)
        return text.replace("\n", " ").strip()

    pdf = PDF()
    pdf.add_page()
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
            row_height = 8
            estimated_height = row_height + len(data) * row_height + 5
            if pdf.get_y() + estimated_height > pdf.h - 20:
                pdf.add_page()
            pdf.ln(3)
            pdf.chapter_title(title_clean.upper())
            headers = list(data[0].keys())
            pdf.set_font("Helvetica", 'B', 9)
            col_widths = [max(pdf.get_string_width(str(h).upper()), max(pdf.get_string_width(str(row[h])) for row in data)) + 6 for h in headers]
            x_start = (pdf.w - sum(col_widths)) / 2
            pdf.set_x(x_start)
            pdf.set_fill_color(220, 230, 240)
            for i, h in enumerate(headers):
                pdf.cell(col_widths[i], 8, h.upper(), border=1, align='C', fill=True)
            pdf.ln()
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
            insight_text = sanitize(data)
            segments = split_insights(insight_text)
            pdf.set_font("Helvetica", 'B', 9)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 6, "[Insights]", ln=True)
            pdf.ln(1)
            pdf.set_text_color(30, 30, 30)
            if not segments:
                pdf.set_font("Helvetica", '', 10)
                pdf.multi_cell(0, 6.5, insight_text)
            else:
                for seg in segments:
                    if ":" in seg:
                        key, val = seg.split(":", 1)
                        pdf.set_font("Helvetica", 'B', 10)
                        pdf.cell(0, 6.5, key.strip() + ":", ln=True)
                        pdf.set_font("Helvetica", '', 10)
                        pdf.multi_cell(0, 6.5, val.strip())
                    else:
                        pdf.set_font("Helvetica", '', 10)
                        pdf.multi_cell(0, 6.5, seg.strip())
                    pdf.ln(1)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)

    pdf_output = BytesIO()
    pdf.output(pdf_output)
    pdf_output.seek(0)

    blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(blob_container)
    try:
        container_client.create_container()
    except Exception:
        pass
    container_client.upload_blob(
        name=file_path, data=pdf_output, overwrite=True,
        content_settings=ContentSettings(content_type="application/pdf")
    )
    return f"{APP_BASE_URL}/chart/{file_name}"


def agent_360_summary(name: str):
    results = {}
    conn = get_conn()
    cursor = conn.cursor()

    # Customer details
    cursor.execute("SELECT TOP 1 Lead_Name, Address, Phone, Email FROM SDI WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)", name, name)
    row = cursor.fetchone()
    customer_details = {"Lead Name": row.Lead_Name, "Address": row.Address, "Phone": row.Phone, "Email": row.Email} if row else {}

    # SDI activity totals
    cursor.execute("""
        SELECT Activity, SUM(ISNULL(Amount, 0)) AS Total_Amount
        FROM SDI WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
        GROUP BY Activity
    """, name, name)
    activity_totals = [{"Activity": r.Activity, "Total_Amount": f"$ {float(r.Total_Amount or 0):.2f}"} for r in cursor.fetchall() if r.Total_Amount != 0.0]
    results['sdi_activity_totals'] = activity_totals

    cursor.execute("SELECT Date, Activity, Description, Quantity, UnitPrice, Commission, Amount, Balance FROM SDI WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)", name, name)
    sdi_data = [{"Date": str(r.Date), "Activity": r.Activity, "Description": r.Description, "Quantity": r.Quantity, "UnitPrice": r.UnitPrice, "Amount": r.Amount} for r in cursor.fetchall()]
    results["sdi_activity_insight"] = get_insight(f"Activity totals: {activity_totals}\nTransaction data: {sdi_data}\nProvide 1-3 crisp insights (Key: value format, no bullets, max 200 words).")

    # Top stocks
    top_stocks = []
    for category, activity in [("Highest_Purchased", "Purchase"), ("Highest_Sold", "Sale"), ("Highest_Dividend_Paying", "Dividend")]:
        cursor.execute(f"""
            SELECT TOP 1 '{category}' AS Category, Description, SUM(ISNULL(Amount,0)) AS Total_Amount
            FROM SDI WHERE (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?)) AND Activity=?
            GROUP BY Description ORDER BY Total_Amount DESC
        """, name, name, activity)
        r = cursor.fetchone()
        if r:
            top_stocks.append({"Category": r.Category, "Description": r.Description, "Total_Amount": f"$ {float(r.Total_Amount or 0):.2f}"})
    results['top_stocks_summary'] = top_stocks
    results["top_stock_insight"] = get_insight(f"Top stocks: {top_stocks}\nTransaction data: {sdi_data}\nProvide 1-3 crisp insights (Key: value format, no bullets, max 200 words).")

    # Stocks purchased + trends
    cursor.execute("""
        SELECT TOP 5 Description, SUM(ISNULL(Amount,0)) AS Total_Amount
        FROM SDI WHERE (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?)) AND Activity='Purchase'
        GROUP BY Description ORDER BY Total_Amount DESC
    """, name, name)
    purchased = cursor.fetchall()
    results["stocks_purchased"] = [{"Description": r.Description, "Total_Amount": f"$ {float(r.Total_Amount or 0):.2f}"} for r in purchased]
    stock_trends = []
    for r in purchased:
        try:
            ticker = yf.Ticker(r.Description)
            end = datetime.datetime.now()
            hist = ticker.history(start=(end - datetime.timedelta(days=15)).strftime('%Y-%m-%d'), end=end.strftime('%Y-%m-%d'))
            closing = hist["Close"].dropna().tail(10).tolist()
            if len(closing) >= 2:
                trend = "rising" if closing[-1] > closing[0] else "falling"
                stock_trends.append(f"{r.Description} - {trend}: {', '.join([f'${p:.2f}' for p in closing])}")
        except Exception as e:
            stock_trends.append(f"Error for {r.Description}: {str(e)}")
    results["stocks_puchased_insight"] = get_insight(f"Stocks purchased: {results['stocks_purchased']}\nTrends: {stock_trends}\nProvide 1-3 crisp insights (Key: value format, no bullets, max 200 words).")

    # SMA activity
    cursor.execute("""
        SELECT CASE
            WHEN LOWER(Description) LIKE 'buy:%' THEN 'Investment Purchase'
            WHEN LOWER(Description) LIKE 'sell:%' THEN 'Investment Sale'
            WHEN LOWER(Activity_Type) IN ('dividend','interest') OR LOWER(Description) LIKE '%coupon%' THEN 'Investment Income'
            WHEN LOWER(Activity_Type) LIKE '%fee%' OR LOWER(Description) LIKE '%fee%' THEN 'Fees'
            WHEN LOWER(Activity_Type) LIKE '%tax%' THEN 'Taxes'
            WHEN LOWER(Activity_Type) = 'deposit' THEN 'Deposit'
            WHEN LOWER(Activity_Type) LIKE '%fx%' THEN 'FX Gain/Loss'
            WHEN LOWER(Activity_Type) = 'withdrawal' THEN 'Withdrawal'
            ELSE 'Others'
        END AS Group_Type, SUM(ISNULL(Amount,0)) AS Total_Amount
        FROM SMA WHERE LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?)
        GROUP BY CASE
            WHEN LOWER(Description) LIKE 'buy:%' THEN 'Investment Purchase'
            WHEN LOWER(Description) LIKE 'sell:%' THEN 'Investment Sale'
            WHEN LOWER(Activity_Type) IN ('dividend','interest') OR LOWER(Description) LIKE '%coupon%' THEN 'Investment Income'
            WHEN LOWER(Activity_Type) LIKE '%fee%' OR LOWER(Description) LIKE '%fee%' THEN 'Fees'
            WHEN LOWER(Activity_Type) LIKE '%tax%' THEN 'Taxes'
            WHEN LOWER(Activity_Type) = 'deposit' THEN 'Deposit'
            WHEN LOWER(Activity_Type) LIKE '%fx%' THEN 'FX Gain/Loss'
            WHEN LOWER(Activity_Type) = 'withdrawal' THEN 'Withdrawal'
            ELSE 'Others'
        END
    """, name, name)
    sma_totals = [{"Group_Type": r.Group_Type, "Total_Amount": f"$ {float(r.Total_Amount or 0):.2f}"} for r in cursor.fetchall()]
    results["sma_activity_totals"] = sma_totals
    cursor.execute("SELECT Date, Activity_Type, Description, Quantity, UnitPrice, Amount, Balance FROM SMA WHERE LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?)", name, name)
    sma_data = [{"Date": str(r.Date), "Activity": r.Activity_Type, "Description": r.Description, "Amount": r.Amount} for r in cursor.fetchall()]
    results["sma_activity_insight"] = get_insight(f"SMA totals: {sma_totals}\nData: {sma_data}\nProvide 1-3 crisp insights (Key: value format, no bullets, max 200 words).")

    # Target vs actual
    cursor.execute("""
        SELECT SUM(amt) AS Actual_Investment FROM (
            SELECT SUM(ISNULL(Amount,0)) AS amt FROM SMA WHERE LOWER(Description) LIKE '%retirement plan contribution%' AND (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?))
            UNION ALL
            SELECT SUM(ISNULL(Debit,0)) FROM Checking WHERE LOWER(Description) LIKE '%goal contribution%' AND (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?))
            UNION ALL
            SELECT SUM(ISNULL(Credit,0)) FROM Savings WHERE LOWER(Description) LIKE '%home goal contribution%' AND (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?))
            UNION ALL
            SELECT SUM(ISNULL(Credit,0)) FROM Managed WHERE LOWER(Description) LIKE '%retirement goal contribution%' AND (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?))
        ) t
    """, name, name, name, name, name, name, name, name)
    r = cursor.fetchone()
    actual = float(r.Actual_Investment or 0)
    results["actual_vs_target_investment"] = [{"Target": "$ 500000.00", "Actual": f"$ {actual:.2f}", "Difference": f"$ {500000.00 - actual:.2f}", "Status": "below target" if actual < 500000 else "above target"}]

    # Payroll bonus
    cursor.execute("SELECT Date, Description, Credit FROM Checking WHERE (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?)) AND LOWER(Description) LIKE '%payroll bonus%'", name, name)
    payroll = [{"Date": str(r.Date), "Description": r.Description, "Credit": f"$ {float(r.Credit or 0):.2f}"} for r in cursor.fetchall()]
    results["payroll_bonus_details"] = payroll
    results["financial_recommendations"] = get_insight(f"Target vs actual: {results['actual_vs_target_investment']}\nPayroll bonuses: {payroll}\nProvide 1-2 financial recommendations (Key: value format, no bullets, max 200 words).")

    # Checking summary
    cursor.execute("""
        SELECT
            SUM(CASE WHEN Debit IS NOT NULL AND Description NOT IN ('Transfer-SMA- Goal Contribution','Transfer-Managed- Goal Contribution','Transfer-Savings- Goal Contribution') THEN ISNULL(Debit,0) ELSE 0 END) AS Home_Expenses,
            SUM(CASE WHEN Debit IS NOT NULL AND Description IN ('Transfer-SMA- Goal Contribution','Transfer-Managed- Goal Contribution','Transfer-Savings- Goal Contribution') THEN ISNULL(Debit,0) ELSE 0 END) AS Home_Goal_Investments,
            SUM(ISNULL(Credit,0)) AS Credit_Inflow
        FROM Checking WHERE LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?)
    """, name, name)
    r = cursor.fetchone()
    checking_summary = [{"Home_Expenses": f"$ {float(r.Home_Expenses or 0):.2f}", "Home_Goal_Investments": f"$ {float(r.Home_Goal_Investments or 0):.2f}", "Credit_Inflow": f"$ {float(r.Credit_Inflow or 0):.2f}"}]
    results["Checking_Summary"] = checking_summary
    cursor.execute("SELECT Date, Description, Debit, Credit, Balance FROM Checking WHERE LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?)", name, name)
    checking_data = [{"Date": str(r.Date), "Description": r.Description, "Debit": r.Debit, "Credit": r.Credit} for r in cursor.fetchall()]
    results["checking_account_insight"] = get_insight(f"Checking summary: {checking_summary}\nData: {checking_data}\nProvide 1-3 crisp insights (Key: value format, no bullets, max 200 words).")

    # Funds
    cursor.execute("""
        SELECT fund_name, total_units, current_nav, current_value, total_invested,
            (current_value - total_invested) AS absolute_return,
            CASE WHEN total_invested != 0 THEN ((current_value - total_invested) / total_invested) * 100 ELSE 0 END AS return_percentage
        FROM Funds WHERE LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?)
    """, name, name)
    funds = cursor.fetchall()
    funds_summary = [{"Fund": r.fund_name, "Units": r.total_units, "NAV": r.current_nav, "Current_Value": f"$ {float(r.current_value or 0):.2f}", "Invested": f"$ {float(r.total_invested or 0):.2f}", "Return": f"$ {float(r.absolute_return or 0):.2f}", "Return_%": f"{float(r.return_percentage or 0):.2f} %"} for r in funds]
    results["Fund_Summary"] = funds_summary
    results["funds_account_insight"] = get_insight(f"Fund summary: {funds_summary}\nProvide 1-3 crisp insights (Key: value format, no bullets, max 200 words).")

    cursor.close()
    conn.close()
    return results, customer_details


@mcp.tool()
def agent_360_summary_with_pdf(name: str) -> dict:
    """Generates a comprehensive 360 financial summary PDF report for a customer."""
    logger.info(f"Tool invoked: agent_360_summary_with_pdf for {name}")
    result, details = agent_360_summary(name)
    safe_name = name.upper().replace(" ", "_")
    file_name = f"360_summary_{safe_name}.pdf"
    url = generate_pdf_report(result, details, BLOB_CONTAINER, f"reports/{file_name}", file_name)
    logger.info(f"PDF report generated: {url}")
    return {"PDF Report URL": url}


async def serve_chart(request: Request):
    filename = request.path_params['filename']
    try:
        blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        blob_client = blob_service.get_blob_client(container=BLOB_CONTAINER, blob=f"reports/{filename}")
        data = blob_client.download_blob().readall()
        return Response(data, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{filename}"'})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=404)


mcp_app = mcp.http_app()

app = Starlette(
    lifespan=mcp_app.lifespan,
    routes=[
        Route("/chart/{filename}", endpoint=serve_chart),
        Mount("/", app=mcp_app),
    ]
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info("🚀 Starting 360 Agent MCP Server...")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
