# GrassCRM — app/routers/expenses.py v8.0.1

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, extract
from sqlalchemy.orm import Session as DBSession, joinedload

from app.database import get_db
from app.models import Expense, ExpenseCategory, TaxPayment, Stage, Deal
from app.schemas import ExpenseCreate, ExpenseUpdate, TaxPaymentCreate, TaxPaymentUpdate
from app.security import get_current_user, require_admin, guard_project, is_won_stage
from app.cache import _cache
from app.config import TAX_RATE

router = APIRouter()


# ── КАТЕГОРИИ ─────────────────────────────────────────────────────────────────
@router.get("/api/expense-categories")
def get_expense_categories(db: DBSession = Depends(get_db), _=Depends(get_current_user)):
    return db.query(ExpenseCategory).order_by(ExpenseCategory.name).all()


# ── РАСХОДЫ ───────────────────────────────────────────────────────────────────
@router.get("/api/expenses")
def get_expenses(year: int, project: str = "pokos", db: DBSession = Depends(get_db), user: dict = Depends(get_current_user)):
    guard_project(project, user)
    q = (db.query(Expense)
         .options(joinedload(Expense.category))
         .filter(extract("year", Expense.date) == year, Expense.project == project)
         .order_by(Expense.date.desc()))
    return [
        {
            "id":       e.id,
            "name":     e.name,
            "amount":   e.amount,
            "category": e.category.name if e.category else "",
            "date":     e.date.isoformat() if e.date else None,
        }
        for e in q.all()
    ]


@router.post("/api/expenses", status_code=201)
def create_expense(data: ExpenseCreate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    category_name = data.category.strip()
    category = None
    if category_name:
        category = db.query(ExpenseCategory).filter(
            func.lower(ExpenseCategory.name) == func.lower(category_name)
        ).first()
        if not category:
            category = ExpenseCategory(name=category_name)
            db.add(category); db.flush()
            _cache.invalidate("expense_categories")

    try:
        parsed_date = _date.fromisoformat(data.date[:10]) if data.date and data.date not in ("null", "None", "") else _date.today()
    except (ValueError, TypeError):
        parsed_date = _date.today()

    new_expense = Expense(
        name=data.name, amount=data.amount, date=parsed_date,
        category_id=category.id if category else None,
        project=data.project or "pokos",
    )
    db.add(new_expense); db.commit(); db.refresh(new_expense)
    _cache.invalidate("expenses", "years")
    return {
        "id":       new_expense.id,
        "name":     new_expense.name,
        "amount":   new_expense.amount,
        "date":     new_expense.date.isoformat() if new_expense.date else None,
        "category": new_expense.category.name if new_expense.category else "",
    }


@router.patch("/api/expenses/{expense_id}")
def update_expense(expense_id: int, data: ExpenseUpdate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(404, "Расход не найден")
    update_data = data.model_dump(exclude_unset=True)
    if "category" in update_data:
        category_name = update_data.pop("category").strip()
        category = None
        if category_name:
            category = db.query(ExpenseCategory).filter(
                func.lower(ExpenseCategory.name) == func.lower(category_name)
            ).first()
            if not category:
                category = ExpenseCategory(name=category_name)
                db.add(category); db.flush()
                _cache.invalidate("expense_categories")
        expense.category_id = category.id if category else None
    if "date" in update_data:
        raw_date = update_data.pop("date")
        if raw_date and raw_date not in ("null", "None", ""):
            try:
                expense.date = _date.fromisoformat(raw_date[:10])
            except (ValueError, TypeError):
                pass
    for key, value in update_data.items():
        setattr(expense, key, value)
    db.commit(); db.refresh(expense)
    _cache.invalidate("expenses", "years")
    return {
        "id":       expense.id,
        "name":     expense.name,
        "amount":   expense.amount,
        "date":     expense.date.isoformat() if expense.date else None,
        "category": expense.category.name if expense.category else "",
    }


@router.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if expense:
        db.delete(expense); db.commit(); _cache.invalidate("expenses", "years")
    return None


# ── НАЛОГИ ────────────────────────────────────────────────────────────────────
@router.get("/api/taxes/summary")
def get_tax_summary(year: int, project: str = "pokos", db: DBSession = Depends(get_db), user: dict = Depends(require_admin)):
    guard_project(project, user)
    cache_key = f"tax_summary:{year}:{project}"
    if (cached := _cache.get(cache_key)) is not None:
        return cached
    won_stage_ids = {s.id for s in db.query(Stage).filter(Stage.project == project).all() if is_won_stage(s)}
    if not won_stage_ids:
        summary = {"revenue": 0, "tax_accrued": 0, "paid": 0, "balance": 0}
        _cache.set(cache_key, summary)
        return summary
    total_revenue = db.query(func.sum(Deal.total)).filter(
        Deal.stage_id.in_(won_stage_ids),
        Deal.project == project,
        extract("year", Deal.deal_date) == year,
    ).scalar() or 0
    tax_accrued = total_revenue * TAX_RATE
    total_paid  = db.query(func.sum(TaxPayment.amount)).filter(TaxPayment.year == year).scalar() or 0
    summary = {
        "revenue":     round(total_revenue, 2),
        "tax_accrued": round(tax_accrued, 2),
        "paid":        round(total_paid, 2),
        "balance":     round(tax_accrued - total_paid, 2),
    }
    _cache.set(cache_key, summary)
    return summary


@router.get("/api/taxes/payments")
def get_tax_payments(year: int, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    cache_key = f"tax_payments:{year}"
    if (cached := _cache.get(cache_key)) is not None:
        return cached
    payments = db.query(TaxPayment).filter(TaxPayment.year == year).order_by(TaxPayment.date.desc()).all()
    _cache.set(cache_key, payments)
    return payments


@router.post("/api/taxes/payments", status_code=201)
def create_tax_payment(payment_data: TaxPaymentCreate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    if payment_data.amount <= 0:
        raise HTTPException(400, "Сумма платежа должна быть положительной.")
    new_payment = TaxPayment(**payment_data.model_dump())
    db.add(new_payment); db.commit(); db.refresh(new_payment)
    _cache.invalidate(f"tax_summary:{payment_data.year}", f"tax_payments:{payment_data.year}", "years")
    return new_payment


@router.patch("/api/taxes/payments/{payment_id}")
def update_tax_payment(payment_id: int, data: TaxPaymentUpdate, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    payment = db.query(TaxPayment).filter(TaxPayment.id == payment_id).first()
    if not payment:
        raise HTTPException(404, "Платёж не найден")
    if data.amount is not None and data.amount <= 0:
        raise HTTPException(400, "Сумма должна быть положительной.")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(payment, key, value)
    db.commit(); db.refresh(payment)
    _cache.invalidate(f"tax_summary:{payment.year}", f"tax_payments:{payment.year}")
    return payment


@router.delete("/api/taxes/payments/{payment_id}", status_code=204)
def delete_tax_payment(payment_id: int, db: DBSession = Depends(get_db), _=Depends(require_admin)):
    payment = db.query(TaxPayment).filter(TaxPayment.id == payment_id).first()
    if payment:
        year = payment.year
        db.delete(payment); db.commit()
        _cache.invalidate(f"tax_summary:{year}", f"tax_payments:{year}")
    return None
