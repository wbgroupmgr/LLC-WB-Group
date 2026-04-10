# class ledgerGeneral
from ledger.ledgerObject import ledgerObject
from ledger.llcCOA import ChartOfAccounts as llcCOA
from ledger.llcAssets import getBal

class ledgerGeneral(ledgerObject):
    '''

    General Ledger Services ... 
    - constructor per the financial pipeline
        - import llcAsset
        - import llcExpense
        - import llcBank
        - reconcile

    - Referennce 
        - llcUsers
        - llcCustomer
    
    - GL Tranaction Records (normalized) - refer to llcCOA.toRecDict() for std definition

    - all LLC DB object must have a obj.to_GL() service call that normalizes their DB into the GL records
    '''
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        self.coa = llcCOA(self.llc)
        self.stdCols = ['tID', 'dt', 'desc', 'amt', 'aType', 'acct', 'acctSub', 'acctType',
                     'refKey', 'refDB', 'refDoc', 'refProp']

    def _ckCOA(self, df = None, col='acct'):
        '''
        Check if account values (col) matches COA 
        '''
        if df is None: df = self.glDF
        for a in df[col].unique():
            if self.coa.get(a) is None:
                print(f"{a:40s} not in COA")

    def classifyAccts(self, df):
        '''
        '''
        # Break down by account
        glSumDF = df.groupby(['acct', 'aType']).amt.sum().unstack()
    
        # compute the totals: bottom, side
        glSumDF.loc['Total'] = glSumDF.sum(axis=0)
        glSumDF['Bal'] = glSumDF.Debit - glSumDF.Credit
        
        return glSumDF.fillna('')

    def classifyAssets(self, df, **kwargs):
        glDF = df.copy()
        # Break down by account
        byCols = kwargs.get('by', ['acctType', 'acct', 'aType'])
        glSumDF = df.groupby(byCols).amt.sum().unstack()
        glSumDF['Bal'] = round(glSumDF.fillna(0).apply(lambda r : r.Debit - r.Credit, axis=1),2)
        glSumDF.loc[('All', 'Total'), :] = glSumDF.sum( axis=0)
        return glSumDF.fillna('')

