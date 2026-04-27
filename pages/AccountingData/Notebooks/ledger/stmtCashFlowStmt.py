# Cash Flow Statement - part of Financial Report 
from IPython.display import display, Markdown

class stmtCashFlow(object):
    
    '''
    <h2> 3. Cash Flow Statement 
    This tracks the actual movement of cash in and out, which differs from profitability. 
    
    - Operating Activities: Cash collected from rent minus cash paid for expenses.
    - Investing Activities: Costs for capital improvements (e.g., new roof).
    - Financing Activities: Mortgage principal payments, owner draws, or new capital contributions. 
    '''
    def __init__(self, fr, **kwargs):
        self.fr = fr # Financial Report object

    def CF_Operating(self):
    
        # Summary of all Acct in GL
        #glAcctDF = self.fr.llc.acctsDF()
    
        # List of accounts
        aList = [dict(Acct='Net Income (from P&L)', amt=0, LedgerAcct='Acct.Cash.Income'),
                 dict(Acct='Less: Depreciation Expense', amt=0, LedgerAcct='Asset.Equity.Depreciation.Expense'),
                 dict(Acct='Less: Account Receivable (unpain rent)', amt=0, LedgerAcct='Acct.Cash.Receivable'),
                 dict(Acct='Less: Security Deposits Held', amt=0, LedgerAcct='Acct.Cash.Payable.Security'),
                ]
        t, df = self.fr._buildGL(aList, Total='Net Cash from Operating Activities')
        
        df.rename(columns=dict(amt='Operations'), inplace=True)
        return t, df
    
    
    def CF_Investing(self):
        '''
        Cash Flow Investing
        (-) Capital Expenditures (e.g., New HVAC system)	($5,000)
        (-) Property Improvements	($2,500)
        Net Cash used in Investing Activities	($7,500)
        '''
    
        tl = "Cash from Investing Activities"
        # List of accounts
        aList = [dict(Acct='Capital Expenditures', amt=0, LedgerAcct='Acct.Equity.Expense.Capital'),
                 dict(Acct=' Property Improvements', amt=0, LedgerAcct='Acct.Equity.Expense.Improvements'),
                ]
        t, df = self.fr._buildGL(aList, Total='Net Cash used in Investing Activities')
        
        df.rename(columns=dict(amt='Operations'), inplace=True)
        return t, df
        
    def CF_Financing(self):
        '''
            Cash from Financing Activities		
            (-) Mortgage Principal Repayments	($4,000)
            (-) Owner Distributions (Draws)	($6,000)
            Net Cash used in Financing Activities	($10,000)
        '''
        tl = "Financing Activities"
        # List of accounts
        aList = [dict(Acct='Mortgage Principal Repayments', amt=0, LedgerAcct='Acct.Cash.Expense.Morgage'),
                 dict(Acct='Owner Distributions (Draws)', amt=0, LedgerAcct='Acct.Cash.Owner.Disbursements'),
                ]
        t, df = self.fr._buildGL(aList, Total='Net Cash used in Financing Activities')
        
        df.rename(columns=dict(amt='Financing'), inplace=True)
        return t, df
    
    def CF_Summary(self):
        
        '''
        CF_Summary		
        Net Increase in Cash for 2025	$2,000
        (+) Cash at Beginning of Year	$8,500
        Cash at End of Year	$10,500
        '''
        # List of accounts
        netCash = self.fr.yeBal - self.fr.begBal
        aList = [dict(Acct=f'Net Increase in Cash for {self.fr.llc.yr}', amt=netCash, LedgerAcct='BalSheet'),
                 dict(Acct='Cash at Beginning of Year', amt=self.fr.begBal, LedgerAcct='BalSheet'),
                ]
        t, df = self.fr._buildGL(aList, Total='Cash at End of Year')
        
        df.rename(columns=dict(amt='Financing'), inplace=True)
        return t, df
    
    def displayCashFlow(self):
    
        oAmt, oDF = self.CF_Operating()
        icAmt, iDF = self.CF_Investing()
        fAmt, fDF = self.CF_Financing()
        fAmt, sDF = self.CF_Summary()

        display(Markdown("\n---"))

        s = f"<h2>{self.fr.llc.objName}: Cash Flow Statement<br>"
        display(Markdown(s))
        s = f"As of Dec 31, {self.fr.llc.yr}<br>"
        display(Markdown(s))
        
        display(Markdown("<h2> Net Cash from Operating Activities"))
        display(oDF)
        display(Markdown("<h2> Cash from Investing Activities"))
        display(iDF)
        display(Markdown("<h2> Cash from Financing Activities"))
        display(fDF)
        display(Markdown("<h2> Cash Flow Summary"))
        display(sDF)