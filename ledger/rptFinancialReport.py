'''
ledger.stmtFinancialReport — Constructed Financial Report & tax-data aggregator.

Relocated from ledger/ → stmt/ per DataModelGuide § 2 (Constructed Financial
Data Objects live in stmt/).  Behaviour is unchanged; only the import path
moved.  Consumers (uillc, irs, util, notebooks) now import:

    from ledger.stmtFinancialReport import stmtFinancialReport

This class still inherits from ledger.ledgerObject rather than the new
stmtDB base so existing callers keep their full interface (notebook display
helpers, taxData(), etc.).  A future pass may harden it onto stmtDB.
'''

import datetime
import json
import pandas as pd
import numpy as np
from IPython.display import display, Markdown

from ledger.ledgerObject import ledgerObject
from ledger.stmtCashFlowStmt import stmtCashFlow

strAmt = lambda n : f"${n:,.0f}"

class rptFinancialReport(ledgerObject):
    def __init__(self, llc, **kwargs):

        # Initialize, set self.llc
        super().__init__(llc, **kwargs)
        self.md = mdIRS

        # Load Balance Sheet form llcAsset DB
        _ = self.llc.assets()
        self.bsDF = self.llc.aObj.getBalanceSheet()

        # ---------------------------------------
        #    Accounting LLC global States
        self.begBal = self.llc._assets()._BegBal()
        self.yeBal = round(self.llc.bk.df.amt.sum(),2)
        self.yeEquity = round(self.bsDF.loc['Total'].Equity,2)
        self.bsDepr = 0 # FIXME depre account name?? self.bsDF.loc['Asset.Asset.Depreciation.Accumulation'].Asset
        self.dtReport = datetime.datetime.now().strftime('%Y.%m.%d')

    #
    # ----------------- ledgerObject overlay

    def _loadGL(self):
        from ledger.stmtGL import ledgerGeneral
        return ledgerGeneral(self.llc)

    def load(self, **kwargs):
        '''
        Return general ledger - glList - derived from mergin & removing dups in llcAssets/llcExpRev
        - llcAssets/llcExpRev are dual account per transaction ledger
        - ledgerGeneral is a single account per transaction ledger
        '''
        
        from ledger.stmtGL import ledgerGeneral
        from ledger.llcExpRev import llcExpRev
        from ledger.llcAssets import llcAssets
        
        
        aObj = llcAssets(self.llc)
        erObj = llcExpRev(self.llc)
        gl = self._loadGL()
        #_aList = aObj.load()
        
        erList = erObj.load()
        aList = aObj.load()
        
        # display transaction with Acct.Rev 
        acctKey = 'Acct.Rev'
        revList = [tDict for tDict in erList if  acctKey in tDict['acct'] or acctKey in tDict['Ledger']]
        print (f"Acct.Rev List: {len(aList)}, revList:{len(revList)}")
        
        # Expand to double-entry GL pairs (drops Ledger, recomputes tID + acctType)
        erList_gl = gl.toDoubleEntry(erList)
        aList_gl = gl.toDoubleEntry(aList)
        
        # Merge: resolve_dups=False → keep all, flag cross-source dups
        glList = gl.mergeGL([erList_gl, aList_gl], resolve_dups=kwargs.get('resolve_dups', True))

        return glList

    def toDF(self):
        # Generate a 
        glList = self.load()
        glDF = pd.DataFrame(glList)
        glDF['acctType'] = glDF.acct.apply(lambda v : self.llc.coa._Type(v))
        return glDF



    #
    # ----------------- notebook services

    def displayProfile(self):
        
        # -----------------------------------------
        #.   Display LLC Profile
        s = f"### Profile - {self.dtReport}\n"
        s += f"- **LLC Name: {self.llc.objName}**\n"
        s += f"- **Year: {self.llc.yr}**\n"
        s += f"- Acct.Equity.Cash Beginning Balance: {self.begBal}\n"
        s += f"- Loaded: GenLedger Loaded (items:{len(self.llc.bk.df)}), BalSheet Loaded(items:{len(bsDF)})"
        display(Markdown(s))

    def _buildIncStmt(self, **kwargs):
        '''
        Build Income Stmt DF
        '''
        glDF = self.toDF()
        cIncSt = ['Asset', 'Equity', 'Liability']
        bshDF = glDF[ ~ glDF.acctType.apply(lambda v : v in cIncSt)]
        return bshDF.groupby(['acctType', 'acct', 'acctSub', 'aType']).amt.sum().unstack()

        if False:
            # OLD 
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

    def _buildIncStmtPerMember(self):
        # load LLC income statement
        isDF = self._buildIncStmt().reset_index()
        bsDF = self._buildBS()
        oList = self.llc.owners()
        oNum = len(oList)
    
        # get depreciation amt
        deprec = bsDF.loc[('Asset','Acct.Fixed.Depreciation.Accum')].Credit
        dList = [deprec]
        
        # Compute the per account Balance 'Bal' column
        isDF['Bal'] = isDF.Credit.fillna(0) - isDF.Debit.fillna(0)
        
        # Extend a column for each member, member ammounts are prorated based on oDict['pct']
        for oDict in oList:
            pct = oDict['pct']
            nm = oDict['nm'][0]
            x = isDF['Bal']* pct
            l = round(isDF.Bal.apply(lambda v : v * pct),2)
            isDF[nm] = l
    
        # Track columns from the beginnning
        cols = list(isDF.columns)
    
        # Compute the Total row (last 4 columns: Bal & num  of owners)
        s = list(round(isDF.iloc[:,-oNum-1:].sum(),2))    
    
        # Compute depreciation pct per member
        dList = [deprec]
        for i in range(len(s)-1):  # num of owners
            oDict = oList[i]
            pct = oDict['pct']
            D = deprec*pct
            dList.append(D)
    
        # Compute Grand Total
        GList = [s-d for s,d in zip(s, dList)]

        distList = [0.0 if v < 0 else v for v in GList]
    
        def newRow(df, label, vList):
            cols = df.columns
            r = [''] * (len(cols)-len(vList))
            r[-3] = label
            #print("46--", r, vList)
            df = pd.DataFrame(r+vList).transpose()
            df.columns = cols
            return df
    
        
        # Wrangle to add (concat) onto IncStmt DF (isDF)
        stDF = newRow(isDF, 'SubTotal', s)
        dDF = newRow(isDF, '- less Depreciation', dList)
        GDF = newRow(isDF, 'Net Income', GList)
        distDF = newRow(isDF, 'Member Distribution', distList)
        isDF = pd.concat([isDF, stDF, dDF, GDF, distDF])
    
        # Wrangle Clean up, delete Credit/Debit 
        isDF.drop(columns=['Credit', 'Debit'],inplace=True)
    
        return isDF.set_index(['acctType', 'acct', 'acctSub'])


    def _buildBS(self, **kwargs):
        '''
        Build Balance Sheet
        '''
        
        glDF = self.toDF()
        cIncSt = ['Asset', 'Equity', 'Liability']
        x = glDF[glDF.acctType.apply(lambda v : v in cIncSt)]
        return x.groupby(['acctType', 'acct', 'aType']).amt.sum().unstack()

        

        if False:
            # OLD Original method

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

            
    # ═══════════════════════════════════════════════════════════════════════
    #  TAX DATA  —  IS / BS / owners aggregates for all IRS tax forms
    # ═══════════════════════════════════════════════════════════════════════

    def taxData(self) -> str:
        """
        Compute all tax-form data from the GL and return as a JSON string.

        Top-level keys
        --------------
        meta      – generated date, LLC name, tax year
        is_data   – Income Statement aggregates (Form 1065 Pg1 + Sched K)
        bs_data   – Balance Sheet aggregates    (Form 1065 Sched L)
        owners    – Partner summary             (Form 1065 Sched M-2 / K-1)

        Usage in Form 1065 workflow
        ---------------------------
            fr  = stmtFinancialReport(llc)
            td  = json.loads(fr.taxData())

            f1065    = Form1065(llc=llc)
            fillDict = f1065._buildFillDict(
                           is_data = td['is_data'],
                           bs_data = td['bs_data'],
                       )
            f1065.saveFILL(fillDict)

        Account taxonomy (for this LLC)
        --------------------------------
        Income Statement accounts (acctType = Income / Expense):
          Acct.Rev.Rent              – gross rental receipts
          Acct.Rev.Interest          – interest earned
          Acct.Rev.Fees.*            – other income (misc fees / refunds)
          Acct.Exp.Repair            – repairs & maintenance
          Acct.Exp.Util              – utilities
          Acct.Exp.Other             – property taxes, licenses, other operating
          Acct.Exp.Operating         – miscellaneous operating expenses
          Acct.Exp.Interest          – mortgage interest (if booked separately)
          Acct.Exp.Salary            – salaries and wages
          Acct.Exp.Depreciation      – depreciation expense for the period

        Balance Sheet accounts (acctType = Asset / Liability / Equity):
          Acct.Cash.Bank             – cash (end-of-year balance)
          Acct.Receivable.*          – accounts receivable
          Acct.Fixed.Tangible.InService   – depreciable building / improvements (cost)
          Acct.Fixed.Tangible.Land        – land (non-depreciable)
          Acct.Fixed.Tangible.InConstruction – construction in progress
          Acct.Fixed.Depreciation.Accum   – accumulated depreciation (contra-asset)
          Acct.Payable.*             – accounts payable
          Acct.Fixed.Tangible.LongTerm    – mortgage / notes payable ≥ 1 year
          Acct.Equity.*              – partners' capital accounts

        Notes
        -----
        • interest_expense: mortgage interest is often booked as a mortgage
          principal reduction (Acct.Fixed.Tangible.LongTerm Debit).  If the LLC
          separates interest into Acct.Exp.Interest, that account is used.
          Otherwise, the CPA must split mortgage payments into principal + interest
          using the amortisation schedule and override this field.

        • distributions_cash: set to max(0, net_income) for a positive-income
          year; zero when net_income ≤ 0 (no distribution from a loss year).

        • cash_contributions: summed from Acct.Equity.Owner.Capital.Funds Credit
          entries in the BS — reflects capital injected during the tax year.

        Returns
        -------
        str   JSON-encoded dict with keys: meta, is_data, bs_data, owners.
        """
        # ── Build IS and BS DataFrames ────────────────────────────────────
        try:
            isDF = self._buildIncStmt()
        except Exception as _e:
            isDF = None

        try:
            bsDF = self._buildBS()
        except Exception as _e:
            bsDF = None

        # ── Safe acct-pattern aggregation helper ──────────────────────────
        def _asum(df, acct_pat: str, col: str) -> float:
            """
            Sum `col` (Debit or Credit) for all rows whose `acct` index level
            contains `acct_pat`.  Returns absolute value, rounded to 2 dp.
            NaN cells are treated as 0.
            """
            if df is None:
                return 0.0
            if col not in df.columns:
                return 0.0
            try:
                lvl  = df.index.get_level_values('acct')
                mask = lvl.str.contains(acct_pat, regex=False, na=False)
                val  = float(df.loc[mask, col].fillna(0).sum())
                return round(abs(val), 2)
            except Exception:
                return 0.0

        # ── IS aggregates ─────────────────────────────────────────────────
        rent_income     = _asum(isDF, 'Acct.Rev.Rent',          'Credit')
        interest_income = _asum(isDF, 'Acct.Rev.Interest',      'Credit')
        fees_income     = _asum(isDF, 'Acct.Rev.Fees',          'Credit')

        total_income    = round(rent_income + interest_income + fees_income, 2)
        other_income    = round(total_income - rent_income - interest_income, 2)

        # Expense lines — match by GL account name
        salaries        = _asum(isDF, 'Acct.Exp.Salary',        'Debit')
        repairs         = _asum(isDF, 'Acct.Exp.Repair',        'Debit')
        utilities       = _asum(isDF, 'Acct.Exp.Util',          'Debit')
        taxes_licenses  = _asum(isDF, 'Acct.Exp.Other',         'Debit')
        depreciation    = _asum(isDF, 'Acct.Exp.Depreciation',  'Debit')
        interest_exp_gl = _asum(isDF, 'Acct.Exp.Interest',      'Debit')
        other_deduct    = _asum(isDF, 'Acct.Exp.Operating',     'Debit')

        # Mortgage interest: use dedicated Exp.Interest when available;
        # fall back to the LongTerm Liability payments (includes principal —
        # CPA must separate using the amortisation schedule).
        if interest_exp_gl == 0.0:
            interest_expense = _asum(bsDF, 'Acct.Fixed.Tangible.LongTerm', 'Debit')
        else:
            interest_expense = interest_exp_gl

        total_expenses  = round(
            salaries + repairs + utilities + taxes_licenses +
            depreciation + interest_expense + other_deduct, 2
        )
        net_income      = round(total_income - total_expenses, 2)

        # ── Owners ────────────────────────────────────────────────────────
        try:
            from ledger.llcOwners import llcOwners
            owners_list = llcOwners(self.llc).load()
        except Exception:
            owners_list = []

        # Cash distributions: only distribute when net income is positive
        distributions_cash = round(
            sum(max(0.0, round(net_income * float(o.get('pct', 0)), 2))
                for o in owners_list),
            2
        )

        # Capital contributions: equity Credits booked during the tax year
        cash_contributions = _asum(
            bsDF, 'Acct.Equity.Owner.Capital.Funds', 'Credit'
        )

        # ── BS aggregates ─────────────────────────────────────────────────
        # Cash: net of all Debits (inflows) and Credits (outflows)
        cash_deb = _asum(bsDF, 'Acct.Cash.Bank', 'Debit')
        cash_crd = _asum(bsDF, 'Acct.Cash.Bank', 'Credit')
        cash     = round(cash_deb - cash_crd, 2)

        # Fixed assets — cost (Debit side of asset accounts)
        buildings   = _asum(bsDF, 'Acct.Fixed.Tangible.InService',     'Debit')
        land        = _asum(bsDF, 'Acct.Fixed.Tangible.Land',          'Debit')
        in_progress = _asum(bsDF, 'Acct.Fixed.Tangible.InConstruction','Debit')
        accum_depr  = _asum(bsDF, 'Acct.Fixed.Depreciation.Accum',     'Credit')

        ar          = _asum(bsDF, 'Acct.Receivable',  'Debit')
        other_assets = round(in_progress, 2)   # expand as COA grows

        total_assets = round(
            cash + ar + buildings - accum_depr + land + other_assets, 2
        )

        # Liabilities
        payables  = _asum(bsDF, 'Acct.Payable',                     'Credit')
        other_liab = _asum(bsDF, 'Acct.Liability.Other',            'Credit')

        # Mortgage balance: net of Credits (origination) minus Debits (payments)
        mtg_crd  = _asum(bsDF, 'Acct.Fixed.Tangible.LongTerm', 'Credit')
        mtg_deb  = _asum(bsDF, 'Acct.Fixed.Tangible.LongTerm', 'Debit')
        mortgage = round(mtg_crd - mtg_deb, 2)

        total_liabilities = round(mortgage + payables + other_liab, 2)

        # Partners' capital: equity Credits minus Debits (draws)
        eq_crd     = _asum(bsDF, 'Acct.Equity', 'Credit')
        eq_deb     = _asum(bsDF, 'Acct.Equity', 'Debit')
        total_equity = round(eq_crd - eq_deb + net_income, 2)

        total_liab_capital = round(total_liabilities + total_equity, 2)

        # ── Assemble result ───────────────────────────────────────────────
        result = {
            "meta": {
                "generated": datetime.date.today().isoformat(),
                "llc":       getattr(self.llc, 'objName', ''),
                "year":      getattr(self.llc, 'yr', ''),
            },
            "is_data": {
                "rent_income":        rent_income,
                "other_income":       other_income,
                "interest_income":    interest_income,
                "total_income":       total_income,
                "salaries":           salaries,
                "repairs":            repairs,
                "taxes_licenses":     taxes_licenses,
                "interest_expense":   interest_expense,
                "depreciation":       depreciation,
                "other_deductions":   other_deduct,
                "total_expenses":     total_expenses,
                "net_income":         net_income,
                "distributions_cash": distributions_cash,
            },
            "bs_data": {
                "cash":               cash,
                "ar":                 ar,
                "buildings":          buildings,
                "accum_depr":         accum_depr,
                "land":               land,
                "other_assets":       other_assets,
                "total_assets":       total_assets,
                "payables":           payables,
                "mortgage":           mortgage,
                "other_liab":         other_liab,
                "total_liabilities":  total_liabilities,
                "total_equity":       total_equity,
                "total_liab_capital": total_liab_capital,
            },
            "owners": {
                "count":              str(len(owners_list)),
                "cash_contributions": cash_contributions,
                "distributions_cash": distributions_cash,
                "detail":             owners_list,
            },
        }

        return json.dumps(result, indent=2)

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
        stmtCashFlow(self).displayCashFlow()

    # ── Trial Balance (v0.2.3.2) ─────────────────────────────────────────────

    def trialBalance(self, view_by: str = 'All'):
        '''
        Return the constructed Trial Balance for the current year.

        The Trial Balance is the standard pre-statement diagnostic: for
        every account it lists Σ Debit and Σ Credit; the grand totals
        must agree for the books to "trial balance".  Built from the
        single source of truth (stmtGeneralLedger with COA seed rows)
        via ``ledger.stmtGeneralLedger.stmtTrialBalance``.

        Parameters
        ----------
        view_by : str
            'All' (default) | 'ByAsset' | 'ByLiability' | 'ByEquity'
            | 'ByIncome' | 'ByExpense'.

        Returns
        -------
        stmtTrialBalance
            Immutable snapshot.  Use ``.to_DF()`` for the DataFrame,
            ``.is_balanced()`` for the zero-sum check, ``.totals()`` for
            the grand totals dict.
        '''
        from ledger.stmtGL import stmtTrialBalance
        return stmtTrialBalance(self.llc, view_by=view_by)

    def displayTrialBalance(self, view_by: str = 'All'):
        '''Render the Trial Balance to the notebook and flag any imbalance.'''
        tb = self.trialBalance(view_by=view_by)

        s = f"<h2>{self.llc.objName}: Trial Balance<br>"
        display(Markdown(s))
        display(Markdown(f"As of Dec 31, {self.llc.yr}<br>"))

        display(tb.to_DF())

        totals = tb.totals()
        if tb.is_balanced():
            display(Markdown(
                f"**✓ Balanced** — Σ Debit {strAmt(totals['Debit'])} "
                f"= Σ Credit {strAmt(totals['Credit'])}"
            ))
        else:
            display(Markdown(
                f"**⚠ NOT balanced** — Σ Debit {strAmt(totals['Debit'])} "
                f"vs Σ Credit {strAmt(totals['Credit'])} "
                f"(diff {strAmt(totals['Diff'])})"
            ))


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

        self.displayTrialBalance()
        self.displayIncomeStatement()
        self.displayBalanceSheet()
        self.displayCashFlow()
        self.displayOtherRF()

        
        
        
        


mdIRS = ''' Tips from stmtFinancialReport

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
