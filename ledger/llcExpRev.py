'''
manage Expenses and Revenues




'''
import os
import pandas as pd
import datetime

from ledger.ledgerDB import ledgerDB


# class llcAssets
class llcExpRev(ledgerDB):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        self.md = mdIRS # Display Tios/Guidelines
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")
            
    def FN(self): 
        fn = os.path.join(self.llc.acctDir(), 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    def bk2Exp(self, df):
        '''
        Import Bk DF and produce a set of new expense entries
          - assign unique ID to each Expense:  dt_amt_Acct_Acct_Sub
                
                
                

                ['tID', 'propNm', 'dt', 'amt', 'aType', 'desc', 'addr', 'propRef',
       'Acct', 'stakeholderPct', 'kwList', 'bal', 'acctType']
        '''

        df == df[df.TransType == 'Exp'].copy()
        
    """
    -----------------------------------------------
    Services for classification and reconcilation
    - call .fetch() before using services
    -----------------------------------------------
    """
    def fetch(self):
        '''
        Load assets into df
        Load aDict to get keys to match
        '''
        try:
            len(self.df)
        except:
            self.df = pd.DataFrame(self.load())
            self.kDict = self._keyDict()

    def _keyDict(self):
        # map dt :: amt, return dict dt:amt 
        df = self.df
        df['dt'] = df.dt.apply(lambda v: datetime.datetime.strptime(v, '%Y.%m.%d').strftime('%m/%d/%Y'))

        kList = df.apply(lambda r : self._key(r), axis=1)
        return {r[0]:r[1] for r in kList}
    
    def _matchBk(self, r):
        # Classify transation
        # Match Bank transaction to asset event based on date(dt) and amount(amt)
        # Return tuple of Acct, SubAcct, and Desc
        (bkKey,ndx) = self._key(r)
        try:
            ndx = self.kDict[bkKey]
            aRow = self.df.iloc[ndx]
            subAcct = aRow.oID
            subAcct = subAcct if subAcct[0] == 'p' else ','.join(aRow.stakeholderPct.keys())
            
            return (aRow.acct, subAcct, aRow.desc)
        except:
            return None
        
mdIRS = '''
<h2> Rental LLLC : Expense Guidelines
- Taxes in a rental LLC financial report are generally classified as `pass-through expenses` (deductions) 
- Not classified as entity-level income taxes
- The LLCs usually do not pay taxes themselves. 
- net income passes to members' personal returns via Schedule E or Schedule C 
    - to avoid double taxation. 

<h3> Key Tax Classifications in Financial Reports:
- **Operating Expenses (Schedule E)**: Property taxes, licenses, and permit fees are categorized as operating expenses to reduce the net rental income, notes IRS (.gov).
- **Pass-Through Income**: Net profit or loss is reported on the owner's personal Form 1040, usually under Schedule E (rental income) or Schedule C (if providing heavy services), notes TurboTax Support.
- **Informational Returns**: 
    - Multi-member LLCs (partnerships) file Form 1065
    - provide a Schedule K-1 to members
    
<h3> Key Considerations:
- **Self-Employment Tax**: 
    - Generally, passive rental income is not subject to self-employment tax
    - exceptions exist for `active management/dealer activity`.
- **Deductions**: 
    - Operating Expenses
    - Property taxes 
    - Mortgage interest
    - maintenance, and 
    - depreciation are deductible business expenses
- **Taxed as Corporation**: 
    - If the LLC elects to be taxed as an S-corp or C-corp, 
    - taxes will be reported differently on company financial statements (e.g., Form 1120S or 1120)

<h3> Sample LLC Expenses
- Advertising: $5,000
- Contract Labor: $10,000
- Depreciation: $2,000
- Office Expenses: $1,500
- Rent: $12,000
- Salaries & Wages: $30,000
- Utilities: $2,500
- Total Expenses: $63,000 
'''
