"""
title: Azure SQL Connector
description: Query all Wealth Management Azure SQL tables — SDI, SMA, Checking, Savings, Managed, Funds
author: WM
version: 2.0.0
"""

import pyodbc
from pydantic import BaseModel


# ─────────────────────────────────────────────
# Database Schema Reference
# ─────────────────────────────────────────────
# Table: SDI
#   Columns: Lead_Name, Lead_ID, Date, Activity, Description,
#            Quantity, UnitPrice, Commission, Amount, Balance, Address, Phone, Email
#   Activities: Purchase, Sale, Dividend
#
# Table: SMA
#   Columns: Lead_Name, Lead_ID, Date, Activity_Type, Description,
#            Quantity, UnitPrice, Amount, Balance
#   Activity_Types: deposit, withdrawal, dividend, interest, fee, tax, fx
#
# Table: Checking
#   Columns: Lead_Name, Lead_ID, Date, Description, Debit, Credit, Balance
#
# Table: Savings
#   Columns: Lead_Name, Lead_ID, Date, Description, Debit, Credit, Balance
#
# Table: Managed
#   Columns: Lead_Name, Lead_ID, Date, Description, Debit, Credit, Balance
#
# Table: Funds
#   Columns: Lead_Name, Lead_ID, fund_name, total_units, current_nav,
#            current_value, total_invested
# ─────────────────────────────────────────────


class Tools:
    class Valves(BaseModel):
        AZURE_SQL_CONNECTION_STRING: str = (
            "Driver={ODBC Driver 18 for SQL Server};"
            "Server=tcp:wm-sql-server-2026.database.windows.net,1433;"
            "Database=WealthManagement;"
            "Uid=sqladmin;"
            "Pwd=WM@wealthmanagement;"
            "Encrypt=yes;TrustServerCertificate=yes;"
            "Connection Timeout=30;"
        )

    def __init__(self):
        self.valves = self.Valves()

    def _conn(self):
        return pyodbc.connect(self.valves.AZURE_SQL_CONNECTION_STRING)

    def run_query(self, query: str) -> str:
        """Run any custom SELECT query against the Azure SQL database."""
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return "No records found."
            header = " | ".join(columns)
            lines = [header, "-" * len(header)]
            for row in rows:
                lines.append(" | ".join(str(v) if v is not None else "" for v in row))
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {str(e)}"

    # ── SDI ──────────────────────────────────

    def get_sdi_summary(self, lead_name: str) -> str:
        """Get SDI activity totals (Purchase, Sale, Dividend) for a lead."""
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Activity, SUM(ISNULL(Amount, 0)) AS Total_Amount
                FROM SDI
                WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
                GROUP BY Activity
            """, lead_name, lead_name)
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return f"No SDI data found for {lead_name}."
            return "\n".join([f"• {r.Activity}: ${float(r.Total_Amount or 0):,.2f}" for r in rows])
        except Exception as e:
            return f"Error: {str(e)}"

    def get_sdi_top_stocks(self, lead_name: str) -> str:
        """Get top 5 purchased, sold, and dividend stocks for a lead from SDI."""
        try:
            conn = self._conn()
            cursor = conn.cursor()
            lines = []
            for category, activity in [("Top Purchases", "Purchase"), ("Top Sales", "Sale"), ("Top Dividends", "Dividend")]:
                cursor.execute("""
                    SELECT TOP 5 Description, SUM(ISNULL(Amount, 0)) AS Total_Amount
                    FROM SDI
                    WHERE (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)) AND Activity = ?
                    GROUP BY Description ORDER BY Total_Amount DESC
                """, lead_name, lead_name, activity)
                rows = cursor.fetchall()
                if rows:
                    lines.append(f"**{category}:**")
                    lines.extend([f"• {r.Description}: ${float(r.Total_Amount or 0):,.2f}" for r in rows])
            conn.close()
            return "\n".join(lines) if lines else f"No stock data found for {lead_name}."
        except Exception as e:
            return f"Error: {str(e)}"

    def get_sdi_transactions(self, lead_name: str) -> str:
        """Get all SDI transactions for a lead."""
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Date, Activity, Description, Quantity, UnitPrice, Amount, Balance
                FROM SDI WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
                ORDER BY Date DESC
            """, lead_name, lead_name)
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return f"No SDI transactions found for {lead_name}."
            lines = ["Date | Activity | Description | Qty | UnitPrice | Amount | Balance"]
            for r in rows:
                lines.append(f"{r.Date} | {r.Activity} | {r.Description} | {r.Quantity} | {r.UnitPrice} | {r.Amount} | {r.Balance}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {str(e)}"

    # ── SMA ──────────────────────────────────

    def get_sma_summary(self, lead_name: str) -> str:
        """Get SMA activity summary grouped by type for a lead."""
        try:
            conn = self._conn()
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
                FROM SMA
                WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
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
            """, lead_name, lead_name)
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return f"No SMA data found for {lead_name}."
            return "\n".join([f"• {r.Group_Type}: ${float(r.Total_Amount or 0):,.2f}" for r in rows])
        except Exception as e:
            return f"Error: {str(e)}"

    # ── Checking ─────────────────────────────

    def get_checking_summary(self, lead_name: str) -> str:
        """Get checking account summary — expenses, goal investments, credit inflow for a lead."""
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN Debit IS NOT NULL AND Description NOT IN (
                        'Transfer-SMA- Goal Contribution',
                        'Transfer-Managed- Goal Contribution',
                        'Transfer-Savings- Goal Contribution'
                    ) THEN ISNULL(Debit, 0) ELSE 0 END) AS Home_Expenses,
                    SUM(CASE WHEN Debit IS NOT NULL AND Description IN (
                        'Transfer-SMA- Goal Contribution',
                        'Transfer-Managed- Goal Contribution',
                        'Transfer-Savings- Goal Contribution'
                    ) THEN ISNULL(Debit, 0) ELSE 0 END) AS Goal_Investments,
                    SUM(ISNULL(Credit, 0)) AS Credit_Inflow
                FROM Checking
                WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
            """, lead_name, lead_name)
            r = cursor.fetchone()
            conn.close()
            if not r:
                return f"No checking data found for {lead_name}."
            return (
                f"• Home Expenses: ${float(r.Home_Expenses or 0):,.2f}\n"
                f"• Goal Investments: ${float(r.Goal_Investments or 0):,.2f}\n"
                f"• Credit Inflow: ${float(r.Credit_Inflow or 0):,.2f}"
            )
        except Exception as e:
            return f"Error: {str(e)}"

    # ── Funds ─────────────────────────────────

    def get_fund_summary(self, lead_name: str) -> str:
        """Get mutual fund holdings, NAV, returns for a lead."""
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT fund_name, total_units, current_nav, current_value, total_invested,
                    (current_value - total_invested) AS absolute_return,
                    CASE WHEN total_invested != 0
                        THEN ((current_value - total_invested) / total_invested) * 100
                        ELSE 0 END AS return_percentage
                FROM Funds
                WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
            """, lead_name, lead_name)
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return f"No fund data found for {lead_name}."
            lines = []
            for r in rows:
                lines.append(
                    f"**{r.fund_name}**\n"
                    f"• Units: {r.total_units}\n"
                    f"• NAV: ${float(r.current_nav or 0):,.2f}\n"
                    f"• Current Value: ${float(r.current_value or 0):,.2f}\n"
                    f"• Invested: ${float(r.total_invested or 0):,.2f}\n"
                    f"• Return: ${float(r.absolute_return or 0):,.2f} ({float(r.return_percentage or 0):.1f}%)"
                )
            return "\n\n".join(lines)
        except Exception as e:
            return f"Error: {str(e)}"

    # ── Target vs Actual ──────────────────────

    def get_target_vs_actual(self, lead_name: str) -> str:
        """Compare actual investment vs $500,000 target across SMA, Checking, Savings, Managed for a lead."""
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SUM(amt) AS Actual_Investment FROM (
                    SELECT SUM(ISNULL(Amount, 0)) AS amt FROM SMA
                    WHERE LOWER(Description) LIKE '%retirement plan contribution%'
                    AND (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
                    UNION ALL
                    SELECT SUM(ISNULL(Debit, 0)) FROM Checking
                    WHERE LOWER(Description) LIKE '%goal contribution%'
                    AND (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
                    UNION ALL
                    SELECT SUM(ISNULL(Credit, 0)) FROM Savings
                    WHERE LOWER(Description) LIKE '%home goal contribution%'
                    AND (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
                    UNION ALL
                    SELECT SUM(ISNULL(Credit, 0)) FROM Managed
                    WHERE LOWER(Description) LIKE '%retirement goal contribution%'
                    AND (LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?))
                ) t
            """, lead_name, lead_name, lead_name, lead_name, lead_name, lead_name, lead_name, lead_name)
            r = cursor.fetchone()
            conn.close()
            actual = float(r.Actual_Investment or 0)
            target = 500000.00
            diff = target - actual
            status = "below target" if diff > 0 else "above target"
            return (
                f"• Target: ${target:,.2f}\n"
                f"• Actual: ${actual:,.2f}\n"
                f"• Difference: ${abs(diff):,.2f} ({status})"
            )
        except Exception as e:
            return f"Error: {str(e)}"

    # ── Customer Details ──────────────────────

    def get_customer_details(self, lead_name: str) -> str:
        """Get customer contact details (name, address, phone, email) from SDI table."""
        try:
            conn = self._conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP 1 Lead_Name, Address, Phone, Email
                FROM SDI
                WHERE LOWER(Lead_Name) = LOWER(?) OR LOWER(Lead_ID) = LOWER(?)
            """, lead_name, lead_name)
            r = cursor.fetchone()
            conn.close()
            if not r:
                return f"No customer details found for {lead_name}."
            return (
                f"• Name: {r.Lead_Name}\n"
                f"• Address: {r.Address}\n"
                f"• Phone: {r.Phone}\n"
                f"• Email: {r.Email}"
            )
        except Exception as e:
            return f"Error: {str(e)}"
