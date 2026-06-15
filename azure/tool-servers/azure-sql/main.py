/cfrom fastapi import FastAPI, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
import pyodbc
import os

app = FastAPI(title="Azure SQL Tool Server", version="1.0.0")

API_KEY = os.environ.get("TOOL_API_KEY", "wm-router-2026-secret")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

AZURE_SQL_CONNECTION_STRING = os.environ.get("AZURE_SQL_CONNECTION_STRING")

def verify_key(auth: str = Security(api_key_header)):
    if not auth or auth.replace("Bearer ", "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

def get_conn():
    return pyodbc.connect(AZURE_SQL_CONNECTION_STRING)

class NameInput(BaseModel):
    name: str

class QueryInput(BaseModel):
    query: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/get_schema", summary="Get all table names and columns in the WealthManagement database")
def get_schema(auth: str = Security(api_key_header)):
    """Returns all tables and their columns with data types. Call this before writing any custom SQL query."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_CATALOG = 'WealthManagement'
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """)
        rows = cursor.fetchall()
        conn.close()
        schema = {}
        for r in rows:
            schema.setdefault(r.TABLE_NAME, []).append(f"{r.COLUMN_NAME} ({r.DATA_TYPE})")
        lines = []
        for table, cols in schema.items():
            lines.append(f"Table: {table}")
            lines.append("  Columns: " + ", ".join(cols))
        return {"result": "\n".join(lines)}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/get_customer_details", summary="Get customer contact details by name")
def get_customer_details(body: NameInput, auth: str = Security(api_key_header)):
    """Get customer name, address, phone, email from SDI table."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT TOP 1 Lead_Name, Address, Phone, Email FROM SDI WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)", body.name, body.name)
        r = cursor.fetchone()
        conn.close()
        if not r:
            return {"result": f"No customer found for {body.name}."}
        return {"result": f"Name: {r.Lead_Name}\nAddress: {r.Address}\nPhone: {r.Phone}\nEmail: {r.Email}"}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/get_sdi_summary", summary="Get SDI activity totals for a lead")
def get_sdi_summary(body: NameInput, auth: str = Security(api_key_header)):
    """Get SDI Purchase, Sale, Dividend totals for a lead."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Activity, SUM(ISNULL(Amount, 0)) AS Total_Amount
            FROM SDI WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
            GROUP BY Activity
        """, body.name, body.name)
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return {"result": f"No SDI data found for {body.name}."}
        return {"result": "\n".join([f"{r.Activity}: ${float(r.Total_Amount or 0):,.2f}" for r in rows])}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/get_sdi_top_stocks", summary="Get top purchased, sold, dividend stocks for a lead")
def get_sdi_top_stocks(body: NameInput, auth: str = Security(api_key_header)):
    """Get top 5 stocks by Purchase, Sale, Dividend from SDI for a lead."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        lines = []
        for category, activity in [("Top Purchases", "Purchase"), ("Top Sales", "Sale"), ("Top Dividends", "Dividend")]:
            cursor.execute("""
                SELECT TOP 5 Description, SUM(ISNULL(Amount, 0)) AS Total_Amount
                FROM SDI WHERE (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)) AND Activity = ?
                GROUP BY Description ORDER BY Total_Amount DESC
            """, body.name, body.name, activity)
            rows = cursor.fetchall()
            if rows:
                lines.append(f"{category}:")
                lines.extend([f"  {r.Description}: ${float(r.Total_Amount or 0):,.2f}" for r in rows])
        conn.close()
        return {"result": "\n".join(lines) if lines else f"No stock data for {body.name}."}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/get_sma_summary", summary="Get SMA activity summary for a lead")
def get_sma_summary(body: NameInput, auth: str = Security(api_key_header)):
    """Get SMA activity grouped by type — Investment Purchase/Sale, Income, Fees, etc."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                CASE
                    WHEN LOWER(Description) LIKE 'buy:%' THEN 'Investment Purchase'
                    WHEN LOWER(Description) LIKE 'sell:%' THEN 'Investment Sale'
                    WHEN LOWER(Activity_Type) IN ('dividend','interest') OR LOWER(Description) LIKE '%coupon%' THEN 'Investment Income'
                    WHEN LOWER(Activity_Type) LIKE '%fee%' OR LOWER(Description) LIKE '%fee%' THEN 'Fees'
                    WHEN LOWER(Activity_Type) LIKE '%tax%' THEN 'Taxes'
                    WHEN LOWER(Activity_Type) = 'deposit' THEN 'Deposit'
                    WHEN LOWER(Activity_Type) LIKE '%fx%' THEN 'FX Gain/Loss'
                    WHEN LOWER(Activity_Type) = 'withdrawal' THEN 'Withdrawal'
                    ELSE 'Others'
                END AS Group_Type,
                SUM(ISNULL(Amount, 0)) AS Total_Amount
            FROM SMA WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
            GROUP BY
                CASE
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
        """, body.name, body.name)
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return {"result": f"No SMA data found for {body.name}."}
        return {"result": "\n".join([f"{r.Group_Type}: ${float(r.Total_Amount or 0):,.2f}" for r in rows])}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/get_fund_summary", summary="Get mutual fund holdings and returns for a lead")
def get_fund_summary(body: NameInput, auth: str = Security(api_key_header)):
    """Get fund name, units, NAV, current value, invested amount, return % for a lead."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fund_name, total_units, current_nav, current_value, total_invested,
                (current_value - total_invested) AS absolute_return,
                CASE WHEN total_invested != 0 THEN ((current_value - total_invested) / total_invested) * 100 ELSE 0 END AS return_pct
            FROM Funds WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
        """, body.name, body.name)
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return {"result": f"No fund data found for {body.name}."}
        lines = []
        for r in rows:
            lines.append(
                f"{r.fund_name}\n"
                f"  Units: {r.total_units} | NAV: ${float(r.current_nav or 0):,.2f}\n"
                f"  Current Value: ${float(r.current_value or 0):,.2f} | Invested: ${float(r.total_invested or 0):,.2f}\n"
                f"  Return: ${float(r.absolute_return or 0):,.2f} ({float(r.return_pct or 0):.1f}%)"
            )
        return {"result": "\n\n".join(lines)}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/get_checking_summary", summary="Get checking account summary for a lead")
def get_checking_summary(body: NameInput, auth: str = Security(api_key_header)):
    """Get home expenses, goal investments, credit inflow from Checking table for a lead."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                SUM(CASE WHEN Debit IS NOT NULL AND Description NOT IN (
                    'Transfer-SMA- Goal Contribution','Transfer-Managed- Goal Contribution','Transfer-Savings- Goal Contribution'
                ) THEN ISNULL(Debit,0) ELSE 0 END) AS Home_Expenses,
                SUM(CASE WHEN Debit IS NOT NULL AND Description IN (
                    'Transfer-SMA- Goal Contribution','Transfer-Managed- Goal Contribution','Transfer-Savings- Goal Contribution'
                ) THEN ISNULL(Debit,0) ELSE 0 END) AS Goal_Investments,
                SUM(ISNULL(Credit,0)) AS Credit_Inflow
            FROM Checking WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
        """, body.name, body.name)
        r = cursor.fetchone()
        conn.close()
        if not r:
            return {"result": f"No checking data found for {body.name}."}
        return {"result": f"Home Expenses: ${float(r.Home_Expenses or 0):,.2f}\nGoal Investments: ${float(r.Goal_Investments or 0):,.2f}\nCredit Inflow: ${float(r.Credit_Inflow or 0):,.2f}"}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/get_target_vs_actual", summary="Compare actual investment vs $500K target for a lead")
def get_target_vs_actual(body: NameInput, auth: str = Security(api_key_header)):
    """Compare actual investment contributions vs $500,000 target across SMA, Checking, Savings, Managed."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(amt) AS Actual FROM (
                SELECT SUM(ISNULL(Amount,0)) AS amt FROM SMA WHERE LOWER(Description) LIKE '%retirement plan contribution%' AND (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?))
                UNION ALL
                SELECT SUM(ISNULL(Debit,0)) FROM Checking WHERE LOWER(Description) LIKE '%goal contribution%' AND (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?))
                UNION ALL
                SELECT SUM(ISNULL(Credit,0)) FROM Savings WHERE LOWER(Description) LIKE '%home goal contribution%' AND (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?))
                UNION ALL
                SELECT SUM(ISNULL(Credit,0)) FROM Managed WHERE LOWER(Description) LIKE '%retirement goal contribution%' AND (LOWER(Lead_Name)=LOWER(?) OR LOWER(Lead_ID)=LOWER(?))
            ) t
        """, body.name, body.name, body.name, body.name, body.name, body.name, body.name, body.name)
        r = cursor.fetchone()
        conn.close()
        actual = float(r.Actual or 0)
        target = 500000.00
        diff = target - actual
        status = "below target" if diff > 0 else "above target"
        return {"result": f"Target: ${target:,.2f}\nActual: ${actual:,.2f}\nDifference: ${abs(diff):,.2f} ({status})"}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}

@app.post("/run_query", summary="Run a custom SELECT query against Azure SQL")
def run_query(body: QueryInput, auth: str = Security(api_key_header)):
    """Execute any custom SELECT query against the WealthManagement database."""
    verify_key(auth)
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(body.query)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return {"result": "No records found."}
        lines = [" | ".join(columns)]
        for row in rows:
            lines.append(" | ".join(str(v) if v is not None else "" for v in row))
        return {"result": "\n".join(lines)}
    except Exception as e:
        return {"result": f"Error: {str(e)}"}
