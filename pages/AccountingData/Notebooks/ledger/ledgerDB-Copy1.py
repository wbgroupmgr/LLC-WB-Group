import os
import datetime
from ledger.ledgerObject import ledgerObject
import numpy as np

class ledgerRecord(object):
    '''
    Create std default GL transaction record 
    '''
    def __init__(self, dbObj, **kwargs):
        self.oID = self.__class__.__name__

    def new(self, **kwargs):
        d = dict = (
            dt = kwargs.get('dt', np.nan),   # Date: The date the expense was paid.
            desc  = kwargs.get('desc', np.nan), # : Description: A short clear description of the item or service 
                                         # (e.g., "HVAC repair," "Monthly Landscaping").
            amt  = kwargs.get('amt', np.nan) ,#  :  transaction amount, always positive

        # ------------- account details
            aType  = kwargs.get('aType', np.nan), # :  Debit or Credit
            acct  = kwargs.get('acct', np.nan), #  : AcctID:  Node1.Node2.Node3 ...  .NodeN
                                          # Refer to llcCOA services for approved accounts. 
                                          # Within DB, acct may be : <nodeSet>.<extraSet>
                                          #- within GL these are seperated into gl.acct and gl.acctExtra
                                          # Nodes beyond the approved set are application specific
                                          # Used in reconciling, ignored by financial bookkeeping pipeline
            acctExtra  = kwargs.get('acctExtra', np.nan), # - sub accts in form Extra1.Extra2 ... ExtraN
                                          #- inForm: _Extra1._Extra2 ... _ExtraN
                                          # - provide extra details in preports
            acctType  = kwargs.get('acctType', np.nan), # COA major categories via COA services 
            refKey  = kwargs.get('refKey', np.nan), # : Key reference per transaction - varies by account
                                          # Acct.Exp : supplier, purchaseOrder[Opt], 
                                          # Acct.Fixed : Owner
                                          # Acct.Rev : Customer or Org (e.g. Bank)
        #-------------- Reference within DB
            tID  = kwargs.get('tID', np.nan), # :    transaction key 
            tDB  = kwargs.get('tDB', np.nan), # 

        #------------- Reference original source of transaction
            refDB  = kwargs.get('refDB', np.nan), # : <DBKey>_<transaction Key 
                                          #(dt_amt)> Payment Method: Check #, Credit Card, or Bank Transfer.
            refDoc  = kwargs.get('refDoc', np.nan), # : Hard Copy location/info 
                                          # - Account specific info - varies per account; long details : 
                                          # - supporting Documentation: Receipt or invoice number.
            refProp  = kwargs.get('refProp', np.nan) # : all transaction must reference a  single property
        )
        # Register unknown keywards wihtin kwargs 
        uList = set(d.keys()) ^ set(kwargs.keys)
        d['unknown'] = {k:v for k,v in kwargs.items() if k in uList}
        return d
        

        
