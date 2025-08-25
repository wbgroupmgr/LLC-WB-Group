import os,sys
from pathlib import Path
dirRE = os.path.dirname(os.getcwd())
if len([p for p in sys.path if p == dirRE]) == 0 :
    sys.path.append(dirRE)

from rewim import rewimLLC
import pandas as pd
from io import StringIO


class property(object):
    def __init__(self, **kwargs):
        self.sqft = kwargs.get('sqft',1080)
        self.sell = kwargs.get('sell', 235000)
        self.assmt = kwargs.get('assmt', 175872)

    def LLC(self, **kwargs):
        return rewimLLC(apprRate = kwargs.get('apprRate',0.07))
        

    def genInfo(self, **kwargs):
        Mkt_Assmt_2025 = self.assmt/self.sell
        Mkt_Assmt_2001 = 37400/53200
        print("Sell:", self.sell)
        print("Assmt:", self.assmt)
        print("2025 Assmt::Mkt:", Mkt_Assmt_2025)
        print("2021 Assmt::Mkt:", Mkt_Assmt_2001)
        print("2025 Assmt@2021:", int(self.sell*Mkt_Assmt_2001))
        print("2025 Sell@2021:", int(self.assmt/Mkt_Assmt_2001))
        print()
        print("Sell-20%:", self.sell*0.8)
        print("Sell-10%:", self.sell*0.9)
        print()

        # identify the market value
        mktvDF = pd.DataFrame([dict(
            pPropHouse=112160,
            pStorage = 300,
            pDeck = 340,
            pLand = 63720
        )], index=['amt']).transpose()
        mktValue = mktvDF.amt.sum()
        print("Market Value (Cty Tax Ofc):", mktValue)
        mktvDF['pct'] = mktvDF.amt/mktValue
        self.df = mktvDF
        return

    def dfAppreciate(self, p, yrEnd = 2025, pct=0.07, **kwargs):
        yrSt = yrEnd + 1 - kwargs.get('years', 5)
        newP = p
        mktV = 0
        csv = "Yr,Value,Appr,YEValue"
        for yr in range(yrSt, yrEnd):
            csv += "\n" + f"{yr},{int(p)},{int(mktV)},{int(newP)}"
            newP = p + mktV
            mktV = newP * pct
            p = newP
        with StringIO(csv) as sio:
            df = pd.read_csv(sio)
        return df

    def appreciationModel(self, p, **kwargs):
        df = self.dfAppreciate(p, **kwargs)
        yrSt = df.iloc[0].Yr
        print(f"Starting Value ({yrSt}):", f"$ {p}")
        print("Future Value @ 6%    :", f"$ {self.dfAppreciate(p, pct=0.06).iloc[-1].YEValue}")
        print("Future Value @ 7%    :", f"$ {self.dfAppreciate(p, pct=0.07).iloc[-1].YEValue}")
        print("Future Value @ 8%    :", f"$ {self.dfAppreciate(p, pct=0.08).iloc[-1].YEValue}")
        self.dfAppr = df

    def roi_RE_Mkt(self, yrs = 5):
        (fvRE, avRE) = self.LLC().ROI(self.sell, 0.06, yrs)
        (fvM, avM) = self.LLC().ROI(self.sell, 0.08, yrs)
        
        rentIncFY = 1500*12*0.8
        rentExpFY = 2200+300*12
        rentInc5Y = rentIncFY*yrs
        rentExp5Y = rentExpFY*yrs
        rentROI = rentInc5Y-rentExp5Y
        roi = round(avRE-avM,2) + rentROI
        df = pd.DataFrame([dict(av = int(avRE), inc=int(rentROI)),
                           dict(av = int(avM), inc=0)], index=['RE', 'Mkt']).transpose()
        df.loc['Sum'] = df.sum(axis=0)
        df.loc['pct.ROI'] = (df.loc['Sum']/self.sell).apply(lambda v: f"{v*100:0.1f}%")
        return df

    def taxModel(self, incNet, taxPct=0.22):
        '''
        Compute RMD by comparing budget income - actual net Income (from tax return)
        '''
        dfInc = pd.DataFrame([dict(incAmy = 50000,
                  incSav = 3000*12,
                  incPen = 59000,
                  incSS = 32000)], index=['amt']).transpose()
        incBase = dfInc.amt.sum()
        dfInc.loc['incRMD'] = incNet - incBase
        return dfInc


    def morgOptions(self, **kwargs):
        '''
        Calculate monthly morgage payment based on options
        Run scenario of Buy/Sell
        '''
        llc = self.LLC(**kwargs)
        llc.invest(buyID='InitialFunds', investors={'Inv_CashFR':10000})
        
        p = self.sell
        llc.buy(sell=p, expenses=p*0.01, interest=0.06, term=30, 
                buyID='buy805HighMesa', 
                investID='Inv_PropFXR', 
                investAmt=kwargs.get('investAmt', 100000))
        
        P = llc.totalDF().loc['principle'].Total
        for i in range(4,8):
            print(f"Morg Principal: $ {P:.0f} at {i}%, Monthly Payment: $ {llc.morgPymt(P, i/100, 30):.0f}")

                
