# IRS Services

## IRS Structure

1. The `irsForm` class in irsForm.py is the core class for all IRS form services.
    - It contains the folder 'self.irsDir' that points to the llc year directory. Use this for FORMDIR in all future code enhancements.
    - the super class irsForm should contain ALL common code.
    - each  form class should contain knowledge unique to that form.
1. IRS API / Methods
    - __init__(llc) - initialize independent of any specific form
    - self.oID = self.__class__.__name__ # the name of the class is the name of the form (files, etc.)
    - FN() -> str : irsDir/{self.oID}_IRS.pdf 
    - **_buildNSpace** (): -> dict ; creates nSpaceDict
        - ftype to be one of the following:
        - 1. text : string : alphanum
        - 2. num : string numeric
        - 3. checkBox : show X over the box field 
        - 4. checkText : show checkmark in field 
        - 5. image : show image (signiture) into field
    - **saveNSpace**(nSpaceDict)
    - **_buildGLMap**(nSpaceDict): -> dict; return glMapDict, restructure from _buildGL2Map()
        - fix so ALL fields are included within glMapDict
        - add a "publish" field to glMapDict that is either True or False
            - where True means the field will be published into the final FILL.pdf.
        - Use best accounting knowledge to determine whether LLC financial objects contain the info.
        - Set to 'CPA:unknown' if it you can not determine whether to publish.
    - **saveGLMap**(glMapDict) ; creates PDF file: irsDir/<form>_GLMap.pdf
    - **_buildFillDict**() -> dict; create fillDict containing all fields with value to be filled
    - **saveFILL**(fillDict) ; creates PDF file: irsDir/<form>_FILL.pdf
1. <form>Obj
    - Each tax form should be a subclass of irsForm, e.g. class Form1065(irsForm)


## Form1065

- be a subclass of irsForm.
- buildGLMap so ALL schB Yes/No default to No,
    - there are 2 checkText fields - the No checkText field should be checked.

## FORM: Sch_K1 
- irs.Sch_K1.py that can run the workflow. Show workflow code.
- is a subclass of Form1065,py
- reuse info from the Form1065; otherwise use info from the BS, IncStmt, OwnerEquity.
-
## Form4562.py
-  Use FIXME for things that can't eb resolved.
-

## LLC tax forms views
- use the fillDict for each form to construct the view of all fields that will be published in the final PDF.




 