# class assetEditor

import os
import json
# Import the editor
from util.uiEditorAssets import uiEditorAssets

class objectEditor(object):
    '''
    Common services for starting Editor from jupyter notebook
    '''
    def __init__(self, obj, **kwargs):
        self.oID = self.__class__.__name__
        self.o = obj
        self.oFN = f"/tmp/{self.oID}_temp.json"


class nbAssetEditor(objectEditor):
    '''
    EditDB Workflow
        - obj = self.o.load()
        - self.saveTemp(obj)
        - EditTemp(self.oFN)

        ------- Post Editing
        - obj = LoadTemp(self.oFN)
        - if no changes, quit
        - self.o.Save(obj)
    '''
        
    def loadTemp(self, **kwargs):
        fn = kwargs.get('FN', self.oFN)
        with open(fn, 'r') as fio:
            return json.load(fio)
        return None

    def saveTemp(self, obj, **kwargs):
        fn = kwargs.get('FN', self.oFN)
        with open(fn, 'w') as fio:
            json.dump(obj, fio)
            
    def editTemp(self, **kwargs):

        # Create editor instance with your JSON file
        self.editor = uiEditorAssets(self.oFN)
        
        # Start the editor (displays inline in notebook)
        self.editor.start(port=8000, height=800, **kwargs)

    def stop(self):
        self.editor.stop()

    def __repr__(self):
        try:
            oList = self.loadTemp()
            fn = self.oFN
        except:
            oList = self.o.load()
            fn = self.o.FN()

        tNum = len(oList)
        bal = sum([d['amt'] for d in oList])

        s = f"{self.o.oID} Editor: Records:{tNum}, Bal:{bal}, FN:{fn}"
        return s
        
        