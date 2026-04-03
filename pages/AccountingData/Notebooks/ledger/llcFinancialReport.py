# llcFinancialReport Services

import datetime
import pandas as pd
import numpy as np
from IPython.display import display, Markdown

from ledger.ledgerObject import ledgerObject
from ledger.llcCashFlowStmt import llcCashFlow

strAmt = lambda n : f"${n:,.0f}"

class llcFinancialReport(ledgerObject):
    def __init__(self, llc, **kwargs):

        # Initialize, set self.llc
        super().__init__(llc, **kwargs)
        self.md = mdIRS

        # Load Balance Sheet form llcAsset DB
        self.bsDF = self.llc.assets().getBalanceSheet()

        # ---------------------------------------
        #    Accounting LLC global States
        self.begBal = self.llc._assets()._BegBal()
        self.yeBal = round(self.llc.bk.df.amt.sum(),2)
        self.yeEquity = round(self.bsDF.loc['Total'].Equity,2)
        self.bsDepr = self.bsDF.loc['Asset.Asset.Depreciation.Accumulation'].Asset
        self.dtReport = datetime.datetime.now().strftime('%Y.%m.%d')

    def displayProfile(self):
        
        # -----------------------------------------
        #.   Display LLC Profile
        s = f"### Profile - {self.dtReport}\n"
        s += f"- **LLC Name: {self.llc.objName}**\n"
        s += f"- **Year: {self.llc.yr}**\n"
        s += f"- Acct.Equity.Cash Beginning Balance: {self.begBal}\n"
        s += f"- Loaded: GenLedger Loaded (items:{len(self.llc.bk.df)}), BalSheet Loaded(items:{len(bsDF)})"
        display(Markdown(s))

    def _buildBS(self, dList, **kwargs):
        '''
        Build Balance Sheet DF
        '''
        # Builf DF of BS
        oDF = pd.DataFrame(dList)

        t = list(oDF.sum(axis=0))[1:]
        col = list(oDF.columns)[1:]
        oDF['Beginning of Year (A)'] = oDF.begYr.apply( lambda n : strAmt(n))
        oDF['End of Year (D)'] = oDF.yeYr.apply( lambda n : strAmt(n))
        oDF.drop(columns = col, inplace=True)
        oDF.set_index('Acct', drop=True, inplace=True)
        oDF.loc[kwargs.get('Total','Totals')] = [strAmt(n) for n in t]
        return dict(begAmt=t[0], yeAmt=t[1]), oDF
    
    def _buildGL(self, glList, **kwargs):
        
        df = pd.DataFrame(glList)
        df.set_index('Acct', drop=True, inplace=True)
        tAmt = df.amt.sum()
        
        t = [strAmt(tAmt) if c == 'amt' else '' for c in df.columns]
        df.loc[kwargs.get('Total','Totals')] = t

       
        return tAmt,df
    def ReaEstateIncome(self):
        '''
        Real Estate Income
        '''
    
        # Summary of all Acct in GL
        glAcctDF = self.llc.acctsDF()
    
        _Acct = 'Acct.Cash.Income'
    
        # List of accounts
        aList = [dict(Acct='Gross Rental Income', amt=glAcctDF.loc['Acct.Cash.Income'], LedgerAcct='Acct.Cash.Income')
                ]
        expList = [dict(Acct='Exp.Advertising', amt=0, LedgerAcct='Acct.Cash.Expense.Advertizing'),
                   dict(Acct='Exp.Management Fees', amt=0, LedgerAcct='Acct.Cash.Expense.FeesMgmt'),
                   dict(Acct='Exp.Repairs&Maint', amt=0, LedgerAcct='Acct.Cash.Expense.Maint'),
                   dict(Acct='Exp.Property Taxes', amt=0, LedgerAcct='Acct.Cash.Expense.PropTax'),
                   dict(Acct='Exp.Insurance', amt=0, LedgerAcct='Acct.Cash.Expense.Ins'),
                   dict(Acct='Exp.MorgInterest', amt=0, LedgerAcct='Acct.Cash.Expense.MorgInt'),
                   dict(Acct='Exp.Utilities', amt=0, LedgerAcct='Acct.Cash.Expense.Util'),
                   dict(Acct='Exp.Ops&Misc', amt=0, LedgerAcct='Acct.Cash.Expense.Misc | Sch.K.L2'),
                  ]

        deprList = [dict(Acct='Less Depreciation', amt=0, LedgerAcct='Acct.Equity.Expense.Depreciation')
                   ]
        
        t, df = self._buildGL(aList+ExpList, Total='Net Taxable Income')
        df.rename(columns=dict(amt='Revenue'), inplace=True)
        return t, df

    
    def Revenue(self):
    
        # Summary of all Acct in GL
        glAcctDF = self.llc.acctsDF()
    
        _Acct = 'Acct.Cash.Income'
    
        # List of accounts
        aList = [dict(Acct='Gross Receipts/Sales', amt=glAcctDF.loc['Acct.Cash.Income'], LedgerAcct='Acct.Cash.Income'),
                 dict(Acct='Less: Returns/Allowances', amt=0, LedgerAcct=np.nan),
                ]
        t, df = self._buildGL(aList, Total='Net Gross Receipts')
        df.rename(columns=dict(amt='Revenue'), inplace=True)
        return t, df

    def COGS(self):
        '''
        Cost of Goods Sold
        - raditional COGS applies to inventory, service businesses use "Cost of Sales" 
        - to track direct labor, subcontractors, and software, allowing them to calculate Gross Profit.
        '''
    
        # Summary of all Acct in GL
        glAcctDF = self.llc.acctsDF()
    
        _Acct = 'Acct.Cash.Income'
    
        # List of accounts
        aList = [dict(Acct='Beginning Inventory', amt=0, LedgerAcct=np.nan),
                 dict(Acct='Purchases', amt=0, LedgerAcct=np.nan),
                dict(Acct='  Less Ending Inventory', amt=0, LedgerAcct=np.nan)
                ]
        t, df = self._buildGL(aList, Total='Total COGS')
        df.rename(columns=dict(amt='COGS'), inplace=True)
        return t, df


    def displayIncomeStatement(self):

        rAmt,rDF = self.Revenue()
        cogsAmt, cogsDF = self.COGS()
        

        # Profit(Loss) Statement (Income Statement)
        s = f"<h2>{self.llc.objName}: Income Statement<br>"
        display(Markdown(s))
        s = f"As of Dec 31, {self.llc.yr}<br>"
        display(Markdown(s))
        
        display(Markdown('<h2>Revenue'))
        display(rDF)
                
        display(Markdown('<h2>Cost of Goods Sold (COGS)'))
        display(cogsDF)

        display(Markdown('<h2>Expense'))
        
        display(Markdown(f'<h2>Gross Profits: {strAmt(rAmt - cogsAmt)}'))

    def Assets(self):
        
        # Import Raw Data From llcAsset DB
        bsDF = self.llc.assets().getBalanceSheet()
        
        # Balance Sheet - Assets 
        aList = [dict(Acct='Acct.Cash', begYr=self.begBal, yeYr=self.yeBal),
                 dict(Acct='Acct.Receivables', begYr=0, yeYr=0),
                 dict(Acct='Acct.Inventory', begYr=0, yeYr=0),
                 dict(Acct='Acct.Equity.FixedAssets', begYr=0, yeYr=self.yeEquity+self.bsDepr),
                 dict(Acct=' Less Depreciation (Accum)', begYr=0, yeYr=-self.bsDepr),
                ]
        return self._buildBS(aList)

    def LiabilitiesAndCapital(self):

        # Balance Sheet - Liabilities & Capital 
        '''
        --------- Example ----------
        |    | Beginning of Year (A)|	End of Year (D)|
        | ---- | ---- | ---- |
        | Accounts Payable	| $2,000	| $1,000 | 
        | Loans Payable | 	$5,000	| $0 | 
        | Partner Capital Accounts |	$25,000|	$45,000|
        |Total Liab. & Capital	|$32,000	| $46,000|
        '''
        lList = [dict(Acct='Acct.Payable', begYr=0, yeYr=0),
                 dict(Acct='Loans.Payable', begYr=0, yeYr=0),
                 dict(Acct='Member Capital Accounts', begYr=0, yeYr=self.yeEquity+self.yeBal),
                ]
        
        return self._buildBS(lList)

    def displayBalanceSheet(self):

        # Balance Sheet - Header
        s = f"<h2>{self.llc.objName}: Balance Sheet<br>"
        display(Markdown(s))
        s = f"As of Dec 31, {self.llc.yr}<br>"
        display(Markdown(s))
        
        # Assets
        aAmtDict, aDF = self.Assets()
        display(Markdown("<h2>Assets"))
        display(aDF)
        
        # Liabilities and Capital
        lAmtDict, lDF = self.LiabilitiesAndCapital()
        display(Markdown("<h2>Liabilities & Capital"))
        display(lDF)

    def displayCashFlow(self):
        llcCashFlow(self).displayCashFlow()


    def RentRoll(self):

        
        lList = [dict(Acct='Units', begYr=0, yeYr=0),
                 dict(Acct='Loans.Payable', begYr=0, yeYr=0),
                 dict(Acct='Member Capital Accounts', begYr=0, yeYr=self.yeEquity+self.yeBal),
                ]
        
        return self._buildBS(lList)

    def displayOtherRF(self):
        '''
        <h2> 4. Other Essential Year-End Items

        - Rent Roll: A summary of all units, tenant names, lease terms, and rental rates.
        - Depreciation Schedule: Calculation of depreciation expense for the property, a major tax deduction.
        - Security Deposit Ledger: A report showing all held security deposits to ensure liability accuracy. 

        '''

        
        s = f"<h2>{self.llc.objName}: Other Essential Year-End Items<br>"
        display(Markdown(s))
        s = f"As of Dec 31, {self.llc.yr}<br>"
        display(Markdown(s))

        display(Markdown("<h2>Rental Units"))
        display(Markdown("<h2>Customers, Terms and Rates(tenants)"))
        display(Markdown("<h2>Depreciation Schedule"))
        display(Markdown("<h2>Security Deposit Ledger"))


    def display(self):
        # Display Financial Report

        s = f"<h2>{self.llc.objName}: Financial Report<br>"
        display(Markdown(s))
        s = f"As of Dec 31, {self.llc.yr}<br>"
        display(Markdown(s))

        self.displayIncomeStatement()
        self.displayBalanceSheet()
        self.displayCashFlow()
        self.displayOtherRF()

        
        
        
        


mdIRS = ''' Tips from llcFinancialReport

<h1> Financial Report Tips/Guidelines

<h2> Inputs

| Account| Desc |AccountingData/ | DB File Name |
| ---- | ---- | ---- | ---- |
| LLC Profile | LLC info, Name, etc,| Parent of LLC Top Dir | LLC_Profile_<llcName>.json |
|General Ledger| List of all transactions<br>derived from YTD/YE Bank download|<year>/Bank/<bank>.csv|
| llcAssets DB | Transactions: Asset, Equity, Liability|Acct|llcAssets.json|
| llcOwners DB | All Members | Acct | llcOwners.json | 
| llcCustomers DB | All Renters, Customers | Acct | llcCustomers.json |
| llcExpenses DB | Expenses, Inventory Transactions | Acct | llcExenses.json | 

<h2> Accounting Guidelines

|       | Asset.Assets  | Asset.Equity  | Asset.Liability | Acct.Cash.Expenses | Acct.Cash.Revenues |
| ---- |  ---- | ---- | ---- | ---- | ---- |
| **Debits** |  Increase | Decrease | Decrease | Increase | Decrease | 
| **Credits** | Decrease | Increase | Increase | Decrease | Increase |
Every transaction must have equal debits and credits. 

<h2> Financial Report to go with Form 1065
- must include financial reports that summarize the business's activity. 
- The core financial reports needed are
    - Profit and Loss Statement (Income Statement)
    - Balance Sheet (Schedule L). 

These reports should reflect the books of the business, which are later reconciled to tax rules on Schedules M-1 and M-2.


<h2> Intro Income Statement

This report shows profitability over the calendar year based on `General Ledger` transactions.
Accumulated Depreciation vs. Depreciation Expense: The balance sheet shows the total depreciation so far (accumulated, while the income statement shows only the depreciation expense for the current period.

- Rental Income: Gross rent collected, including laundry or parking fees.
- Operating Expenses: Property taxes, insurance, repairs/maintenance, property management fees, and utilities.
- Net Operating Income (NOI): Total Income minus Operating Expenses.
- Non-Operating Expenses: Mortgage interest (not principal, depreciation, and amortization.
    - Depreciation Expense for the current period
- Net Income/Loss: The final profit or loss after all expenses, including interest and depreciation.

<h2> 3. Cash Flow Statement 
This tracks the actual movement of cash in and out, which differs from profitability. 

<h4> Operating Activities: Cash collected from rent minus cash paid for expenses.
Cash from Operating Activities	Net Income (from P&L)	$12,000

Adjustments for non-cash items:	
(+) Depreciation Expense	$6,500
Changes in Working Capital:	
(-) Increase in Accounts Receivable (Unpaid Rent)	($1,000)
(+) Increase in Security Deposits Held	$2,000
Net Cash from Operating Activities	$19,500
```

<h3> Investing Activities: Costs for capital improvements (e.g., new roof).
````
Cash from Investing Activities		
(-) Capital Expenditures (e.g., New HVAC system)	($5,000)
(-) Property Improvements	($2,500)
Net Cash used in Investing Activities	($7,500)
````

<h3> Financing Activities: Mortgage principal payments, owner draws, or new capital contributions. 
````
Cash from Financing Activities		
(-) Mortgage Principal Repayments	($4,000)
(-) Owner Distributions (Draws)	($6,000)
Net Cash used in Financing Activities	($10,000)

<h3> Summary Cash Flow
````
Summary		
Net Increase in Cash for 2025	$2,000
(+) Cash at Beginning of Year	$8,500
Cash at End of Year	$10,500
````

<h2> 4. Other Essential Year-End Items

- Rent Roll: A summary of all units, tenant names, lease terms, and rental rates.
- Depreciation Schedule: Calculation of depreciation expense for the property, a major tax deduction.
- Security Deposit Ledger: A report showing all held security deposits to ensure liability accuracy. 

'''
