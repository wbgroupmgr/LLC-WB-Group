'''
utilFinancialStyleGuide — Financial Report Style Aid for LLC Accounting Views.

Provides two classes:

  FRStyleGuide        — Documents and returns CSS / style metadata for the
                        six Standard Line Types used across all financial
                        statement views (IS, BS, Equity, PropertyEquity, etc.)

  TransactionStyleGuide — Documents and returns per-transaction row styling
                          based on the transaction's refDB source reference.

Timestamp of last change: 2026.04.16
'''

from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# FRStyleGuide — Standard Line Types
# ─────────────────────────────────────────────────────────────────────────────

class FRStyleGuide:
    '''
    Standard Line Type Usage for Financial Report views.

    Six line types are defined, each with a CSS class name, a human-readable
    label, a description, and a sample inline style dictionary:

    ┌───────────────┬─────────────────────────────────────────────────────────┐
    │ LINE TYPE     │ USAGE                                                    │
    ├───────────────┼─────────────────────────────────────────────────────────┤
    │ Major         │ Thick solid black separator. Used before major section   │
    │               │ headings (Income, Expenses, Assets, Liabilities, etc.)  │
    ├───────────────┼─────────────────────────────────────────────────────────┤
    │ Minor         │ Thin gray separator. Used between sub-groups within a   │
    │               │ section; lighter visual weight than Major.              │
    ├───────────────┼─────────────────────────────────────────────────────────┤
    │ Transaction   │ Standard transaction/data row. No separator lines.      │
    │               │ Text color driven by TransactionStyleGuide (refDB).     │
    ├───────────────┼─────────────────────────────────────────────────────────┤
    │ Total         │ Single overline above the sum.  Used for account-level  │
    │               │ totals (sum of transaction rows within one account).    │
    ├───────────────┼─────────────────────────────────────────────────────────┤
    │ SubTotal      │ Multi-index summation.  Bold, tinted background.        │
    │               │ Used at the section level (Total Income, Total Expense).│
    ├───────────────┼─────────────────────────────────────────────────────────┤
    │ GrandTotal    │ Double thin black underline at the bottom.  Used for    │
    │               │ the final bottom-line figure (Net Income, Net Worth).   │
    └───────────────┴─────────────────────────────────────────────────────────┘
    '''

    # CSS class names (match what templates use)
    CSS_MAJOR       = 'fr-line-major'
    CSS_MINOR       = 'fr-line-minor'
    CSS_TRANSACTION = 'fr-line-transaction'
    CSS_TOTAL       = 'fr-line-total'
    CSS_SUBTOTAL    = 'fr-line-subtotal'
    CSS_GRANDTOTAL  = 'fr-line-grandtotal'

    # Map of line-type name → style descriptor
    LINE_TYPES: Dict[str, Dict[str, Any]] = {
        'Major': {
            'css_class':   CSS_MAJOR,
            'label':       'Major Separator',
            'description': 'Thick solid black top border. Marks the start of a major section '
                           '(e.g., Income, Expenses, Assets). High visual weight.',
            'border_top':  '3px solid #111827',
            'background':  '#f3f4f6',
            'color':       '#111827',
            'font_weight': '700',
            'font_size':   '13px',
            'text_transform': 'uppercase',
            'letter_spacing': '0.06em',
        },
        'Minor': {
            'css_class':   CSS_MINOR,
            'label':       'Minor Separator',
            'description': 'Thin gray top border. Marks the start of a sub-group within '
                           'a section. Lower visual weight than Major.',
            'border_top':  '1px solid #d1d5db',
            'background':  'transparent',
            'color':       '#6b7280',
            'font_weight': '600',
            'font_size':   '12px',
            'text_transform': 'none',
            'letter_spacing': '0.02em',
        },
        'Transaction': {
            'css_class':   CSS_TRANSACTION,
            'label':       'Transaction Row',
            'description': 'Standard data row with no separator. Text color is determined '
                           'by TransactionStyleGuide based on refDB. Default: black.',
            'border_top':  'none',
            'background':  'transparent',
            'color':       '#111827',
            'font_weight': 'normal',
            'font_size':   '13px',
            'text_transform': 'none',
            'letter_spacing': 'normal',
        },
        'Total': {
            'css_class':   CSS_TOTAL,
            'label':       'Account Total',
            'description': 'Single thin overline above the sum amount. Used for account-level '
                           'totals (the sum of transactions within one GL account).',
            'border_top':  '1px solid #374151',
            'background':  '#f9fafb',
            'color':       '#1f2937',
            'font_weight': '600',
            'font_size':   '13px',
            'text_transform': 'none',
            'letter_spacing': 'normal',
        },
        'SubTotal': {
            'css_class':   CSS_SUBTOTAL,
            'label':       'Sub-Total',
            'description': 'Multi-index summation row. Bold text on a tinted background. '
                           'Used at the section level (e.g., Total Income, Total Expenses).',
            'border_top':  '2px solid #93c5fd',
            'background':  '#eff6ff',
            'color':       '#1e40af',
            'font_weight': '700',
            'font_size':   '14px',
            'text_transform': 'none',
            'letter_spacing': 'normal',
        },
        'GrandTotal': {
            'css_class':   CSS_GRANDTOTAL,
            'label':       'Grand Total',
            'description': 'Double thin black underline at the bottom. The ultimate bottom-line '
                           'figure: Net Income, Net Worth, etc. Maximum visual weight.',
            'border_top':  '3px double #111827',
            'background':  '#1e3a8a',
            'color':       '#ffffff',
            'font_weight': '800',
            'font_size':   '15px',
            'text_transform': 'none',
            'letter_spacing': 'normal',
        },
    }

    # ── CSS snippet that templates can embed ────────────────────────────────

    CSS_BLOCK = '''
/* ── FRStyleGuide — Standard Line Types ── */
.fr-line-major {
    border-top: 3px solid #111827;
    background: #f3f4f6;
    color: #111827;
    font-weight: 700;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.fr-line-minor {
    border-top: 1px solid #d1d5db;
    color: #6b7280;
    font-weight: 600;
    font-size: 12px;
}
.fr-line-transaction {
    /* color set dynamically by TransactionStyleGuide */
    font-weight: normal;
    font-size: 13px;
}
.fr-line-total {
    border-top: 1px solid #374151;
    background: #f9fafb;
    color: #1f2937;
    font-weight: 600;
}
.fr-line-subtotal {
    border-top: 2px solid #93c5fd;
    background: #eff6ff;
    color: #1e40af;
    font-weight: 700;
    font-size: 14px;
}
.fr-line-grandtotal {
    border-top: 3px double #111827;
    background: #1e3a8a;
    color: #ffffff;
    font-weight: 800;
    font-size: 15px;
}
'''

    # ── Public interface ────────────────────────────────────────────────────

    @classmethod
    def get(cls, line_type: str) -> Dict[str, Any]:
        '''Return the style descriptor for a named line type.'''
        return cls.LINE_TYPES.get(line_type, cls.LINE_TYPES['Transaction'])

    @classmethod
    def css_class(cls, line_type: str) -> str:
        '''Return the CSS class name for a named line type.'''
        return cls.get(line_type).get('css_class', cls.CSS_TRANSACTION)

    @classmethod
    def all_types(cls) -> List[str]:
        '''Return all defined line type names in display order.'''
        return ['Major', 'Minor', 'Transaction', 'Total', 'SubTotal', 'GrandTotal']

    @classmethod
    def css_snippet(cls) -> str:
        '''Return the full CSS block string for embedding in a <style> tag.'''
        return cls.CSS_BLOCK


# ─────────────────────────────────────────────────────────────────────────────
# TransactionStyleGuide — Per-Transaction Row Styling
# ─────────────────────────────────────────────────────────────────────────────

class TransactionStyleGuide:
    '''
    Per-transaction row text styling based on the refDB field.

    The refDB field identifies the source ledger or reference database that
    a transaction originates from, enabling consistent color-coding across
    all financial views.

    Color Schema:
    ┌───────────────────────────────┬───────────┬──────────────────────────────┐
    │ refDB values                  │ Color     │ Meaning                      │
    ├───────────────────────────────┼───────────┼──────────────────────────────┤
    │ llcAsset, llcOwner,           │ Blue      │ Internal LLC ledger records  │
    │ llcCustomer                   │ #1d4ed8   │ (assets, owners, customers)  │
    ├───────────────────────────────┼───────────┼──────────────────────────────┤
    │ (empty / None)                │ Black     │ Default — no external source │
    │                               │ #111827   │                              │
    ├───────────────────────────────┼───────────┼──────────────────────────────┤
    │ worksheet, ws, report,        │ Green     │ Cross-worksheet / computed   │
    │ calc, computed                │ #15803d   │ references (reports only)    │
    ├───────────────────────────────┼───────────┼──────────────────────────────┤
    │ external, ext, warning,       │ Red       │ External link or critical    │
    │ error, alert                  │ #b91c1c   │ warning flag                 │
    └───────────────────────────────┴───────────┴──────────────────────────────┘
    '''

    # Canonical color values
    COLOR_BLUE  = '#1d4ed8'   # Internal LLC ledger (llcAsset / llcOwner / llcCustomer)
    COLOR_BLACK = '#111827'   # Default — no refDB
    COLOR_GREEN = '#15803d'   # Worksheet / computed cross-references
    COLOR_RED   = '#b91c1c'   # External sources or critical warnings

    # CSS class names
    CSS_BLUE  = 'txn-refdb-blue'
    CSS_BLACK = 'txn-refdb-black'
    CSS_GREEN = 'txn-refdb-green'
    CSS_RED   = 'txn-refdb-red'

    # refDB keyword sets (all lowercase for case-insensitive matching)
    _BLUE_REFS  = frozenset({'llcasset', 'llcowner', 'llccustomer'})
    _GREEN_REFS = frozenset({'worksheet', 'ws', 'report', 'calc', 'computed'})
    _RED_REFS   = frozenset({'external', 'ext', 'warning', 'error', 'alert'})

    # Style descriptors for each color
    STYLES: Dict[str, Dict[str, Any]] = {
        'blue': {
            'css_class':   CSS_BLUE,
            'color':       COLOR_BLUE,
            'label':       'Internal LLC Ledger',
            'description': 'Transaction sourced from an internal LLC ledger: '
                           'llcAsset, llcOwner, or llcCustomer.',
            'refdb_examples': ['llcAsset', 'llcOwner', 'llcCustomer'],
        },
        'black': {
            'css_class':   CSS_BLACK,
            'color':       COLOR_BLACK,
            'label':       'Default (No refDB)',
            'description': 'No refDB value — transaction has no external source reference. '
                           'Standard default styling.',
            'refdb_examples': ['', None],
        },
        'green': {
            'css_class':   CSS_GREEN,
            'color':       COLOR_GREEN,
            'label':       'Worksheet / Computed Reference',
            'description': 'Transaction is a cross-worksheet reference or computed value '
                           '(used in reports and roll-ups). Read-only context.',
            'refdb_examples': ['worksheet', 'ws', 'report', 'calc', 'computed'],
        },
        'red': {
            'css_class':   CSS_RED,
            'color':       COLOR_RED,
            'label':       'External / Warning',
            'description': 'Transaction references an external source or carries a '
                           'critical warning flag requiring attention.',
            'refdb_examples': ['external', 'ext', 'warning', 'error', 'alert'],
        },
    }

    # ── CSS block ────────────────────────────────────────────────────────────

    CSS_BLOCK = '''
/* ── TransactionStyleGuide — refDB-based row coloring ── */
.txn-refdb-blue  { color: #1d4ed8; }
.txn-refdb-black { color: #111827; }
.txn-refdb-green { color: #15803d; }
.txn-refdb-red   { color: #b91c1c; font-weight: 600; }
'''

    # ── Public interface ─────────────────────────────────────────────────────

    @classmethod
    def classify(cls, ref_db: Optional[str]) -> str:
        '''
        Given a refDB string (or None), return the color category name:
        'blue' | 'black' | 'green' | 'red'.
        '''
        if not ref_db:
            return 'black'
        key = str(ref_db).strip().lower()
        if key in cls._BLUE_REFS:
            return 'blue'
        if key in cls._GREEN_REFS:
            return 'green'
        if key in cls._RED_REFS:
            return 'red'
        # Fallback: any unrecognised refDB is treated as external → red
        return 'red'

    @classmethod
    def css_class(cls, ref_db: Optional[str]) -> str:
        '''Return the CSS class name for a given refDB value.'''
        category = cls.classify(ref_db)
        return cls.STYLES[category]['css_class']

    @classmethod
    def color(cls, ref_db: Optional[str]) -> str:
        '''Return the hex color string for a given refDB value.'''
        category = cls.classify(ref_db)
        return cls.STYLES[category]['color']

    @classmethod
    def style_attr(cls, ref_db: Optional[str]) -> str:
        '''
        Return an inline HTML style attribute string, e.g.
        'color:#1d4ed8' — convenient for Jinja2 templates.
        '''
        return f'color:{cls.color(ref_db)}'

    @classmethod
    def get(cls, ref_db: Optional[str]) -> Dict[str, Any]:
        '''Return the full style descriptor dict for a given refDB value.'''
        return cls.STYLES[cls.classify(ref_db)]

    @classmethod
    def css_snippet(cls) -> str:
        '''Return the full CSS block string for embedding in a <style> tag.'''
        return cls.CSS_BLOCK
