# Architectural Design Document: Intelligent Tax Form Modeling System (ITFMS)**Document Status:** Blueprint  

**Target Architecture:** Rules-Based to LLM-Agentic Ecosystem  

## 1. Executive Summary & Design Philosophy

The Intelligent Tax Form Modeling System (ITFMS) transitions legacy IRS mapping rules (`bookNS<form>.json`) into a highly decoupled, composable, and deterministic data infrastructure. 

The architecture is built on three core tenets:
- 1. **Composition Over Inheritance**: Forms are coordinators of small, reusable, isolated Section Models.
- 2. **Decoupling Data from Logic**: Schemas define shapes; stateless service pipelines execute calculations and workflows.
  3. **Strict Boundary Anchoring**: Large Language Models (LLMs) are used strictly for text extraction and translation into deterministic, validated object models. They never perform mathematical calculations.

## 2. High-Level System Architecture
The system evolves through three decoupled layers, moving data from unstructured source material to verified financial objects.


[Phase 3: LLM Layer] ➔ Extracted Text JSON (Forces schema format)
│
▼
[Phase 1: Domain Layer] ➔ Validated Form & Section Models (Schema/Type enforcement)
│
▼
[Phase 2: Graph Layer] ➔ Dependency DAG & Calculation Engines (Deterministic execution)


---

## 3. Data Architecture: Composable Section Modeling

Forms are broken down into **Sections per Form**, implemented as independent nested models. This approach optimizes LLM token context, allows localized validation, and mirrors IRS visual structures.

### Structural UML Mapping

````
+------------------------------------+
| Form1040Model | <--- Parent Orchestrator
+------------------------------------+
| - year: int                        |
| - filing_status: FilingStatusSec   | <--- Composition
| - income: IncomeSection            | <--- Composition
+------------------------------------+
                 │
        ┌────────┴────────┐
        ▼                 ▼
+----------------+ +---------------+
|FilingStatusSec | | IncomeSection | <--- Child Section Models
+----------------+ +---------------+
| - is_single    | | - w2_wages    |
| - is_mfj       | | - tax_interest|
+----------------+ +---------------+
````

---

## 4. Implementation Blueprint (Python / Pydantic v2)

This implementation converts flat JSON parsing logic into nested domain models ready for tool-calling integration.

```python
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
import re

# ==========================================
# PHASE 1: SECTION MODELS (Atomic Buildings Blocks)
# ==========================================

class FilingStatusSection(BaseModel):
    """Corresponds to Page 1, Lines 1-5 of Form 1040."""
    is_single: bool = Field(default=False, description="Line 1: Single filing status checkbox")
    is_married_filing_jointly: bool = Field(default=False, description="Line 2: Joint filing status checkbox")


class DependentItem(BaseModel):
    """Reusable structure for single dependent sub-grids."""
    first_name: str = Field(..., description="Dependent first name")
    last_name: str = Field(..., description="Dependent last name")
    ssn: str = Field(..., description="Social Security Number formatted as XXX-XX-XXXX")

    @field_validator('ssn')
    @classmethod
    def validate_ssn(cls, v: str) -> str:
        if not re.match(r"^\d{3}-\d{2}-\d{4}\$", v):
            raise ValueError("SSN must match XXX-XX-XXXX format")
        return v


class IncomeSection(BaseModel):
    """Corresponds to Lines 1z through 9 of Form 1040."""
    w2_wages: float = Field(default=0.0, description="Line 1z: Total digital W-2 wages")
    taxable_interest: float = Field(default=0.0, description="Line 2b: Taxable interest")


# ==========================================
# PHASE 1: FORM ORCHESTRATOR (Composite Model)
# ==========================================

class Form1040Model(BaseModel):
    """Top-level IRS Form 1040 Domain Schema."""
    tax_year: int = Field(default=2026, description="The specific IRS filing year")
    filing_status: FilingStatusSection = Field(..., description="Filing Status Section block")
    dependents: List[DependentItem] = Field(default_factory=list, description="List of claimed dependents")
    income: IncomeSection = Field(..., description="Income gathering block")


# ==========================================
# PHASE 2: STATELESS CALCULATION SERVICE
# ==========================================

class Form1040Calculator:
    """Stateless service responsible for mathematical evaluation and internal form logic."""
    
    @staticmethod
    def calculate_total_income(form: Form1040Model) -> float:
        # Math is safely separated from the raw data object definitions
        return form.income.w2_wages + form.income.taxable_interest
```

---

## 5. Computation Lifecycle: The Directed Acyclic Graph (DAG)

Tax fields are inherently dependent on other fields across various forms. The computational engine represents these relationships as a DAG to track evaluation lines.

````
[Form W2: Box 1] ───┐
                    ▼
        [Schedule B: Line 4] ──➔ [Form 1040: Line 1z (W2 Wages)] ──➔ [Form 1040: Line 9 (Total Income)]
                                        ▲
                                        [Form 1040: Line 2b] ────────┘
````

1.  **Node Extraction**: Every field in a Section Model converts into a DAG node (`Form_ID.Section_ID.Field_ID`).
2.  **Metadata Injection**: Legacy parsing instructions derived from `bookNS.json` are attached as immutable metadata fields onto individual graph nodes.
3.  **Topological Sort**: The calculations engine maps computation tasks based on cross-form line dependencies.

---

## 6. Phase 3 Evolution: The LLM Specialization Framework

Rather than leveraging generative AI for calculations, LLMs are limited strictly to context translation, extracting unstructured financial data into structural JSON templates matching the Section Models.


[Unstructured Data]
(W2 PDFs, Receipts, Chat)
│
▼
┌──────────────────┐
│ Form Agent Router│ ──➔ Identifies target form (e.g., Form 1040)
└──────────────────┘
│
▼
┌────────────────────┐
│ Section Allocator │ ──➔ Breaks payload processing into targeted Sections
└────────────────────┘
│
┌──────┴──────┐
▼ ▼
[LLM Worker] [LLM Worker]
(Extracts (Extracts
Status Sec) Income Sec)
│ │
└──────┬──────┘
▼
┌────────────────────┐
│ Pydantic Engine │ ──➔ Schema validation check loop
└────────────────────┘
│
┌───────┴───────┐
Pass Fail
▼ ▼
[To Graph Logic] [Error Log Fed back to LLM Prompt for auto-correction]


### Agentic Scaling Best Practices
*   **Structured Output Tooling**: Leverage functional pipelines like OpenAI Structured Outputs, Instructor, or Outlines. Bind the target generation schema directly to the atomic **Section Model** rather than the parent Form Model.
*   **Localized Vector Stores (RAG)**: Create decoupled indices for vector storage categorized by form instructions. When executing the `IncomeSection` LLM pipeline, only pass context parsed from IRS Publication 17 (Your Income) and Form 1040 Instructions for lines 1-9.
*   **Self-Correction Runtime Loop**: If an LLM returns data failing runtime validation (e.g., an invalid SSN format), intercept the Pydantic `ValidationError` and feed it back dynamically into the next LLM prompt iteration for automated correction.

To implement this template effectively, do you want to explore the Graph Layer setup using a library like NetworkX, or should we look closely at configuring the LLM structured output validation engine?

