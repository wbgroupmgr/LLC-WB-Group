# -*- coding: utf-8 -*-
'''
md2pdf services 

pip install md2pdf

Dependencies:
markdown2, weasyprint  services

Orig: python3.13/site-packages/md2pdf/core.py

'''
from __future__ import unicode_literals

from markdown2 import markdown, markdown_path
from weasyprint import HTML, CSS
import warnings

    
class md(object):
    def __init__(self, mdStr, **kwargs):
        self.mdStr = mdStr if type(mdStr) is str else mdStr.read()

        # Get styles
        fnCSS = kwargs.get('fnCSS', None)
        self.css = [CSS(filename=fnCSS)] if fnCSS else []

        # Base url for images
        self.base_url = kwargs.get('base_url', '.')

    def html(self, **kwargs):
        
        # Convert markdown to html
        raw_html = ''
        extras = ['cuddled-lists', 'tables', 'footnotes']
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw_html = markdown(self.mdStr, extras=extras)
    
        if not len(raw_html):
            print('WARNING: no markdown generated')
            raw_html = ''

        fnHTML = kwargs.get('fnHTML', None)
        if fnHTML is None:
            return raw_html
        with open(fnHTML, 'w') as fio:
            fio.write(html)
        return
        
    def pdf(self, **kwargs):

        raw_html = kwargs.get('html', self.html(**kwargs))

        # Weasyprint HTML object
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            html = HTML(string=raw_html, base_url=self.base_url)

        fnPDF = kwargs.get('fnPDF', None)
        if fnPDF is None:
            # return pdf string
            return html.write_pdf(stylesheets=self.css)
               
        # Write PDF to file
        html.write_pdf(fnPDF, stylesheets=css)
        return
