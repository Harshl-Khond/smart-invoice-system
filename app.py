import base64
from flask import Flask, render_template, request, redirect, url_for, send_file, flash,session
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import datetime, timedelta
import io
import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message

# ------------------------
# Firebase Initialization
# ------------------------
cred = credentials.Certificate("serviceAccountKey.json")  # <-- Your secure key file
firebase_admin.initialize_app(cred)
db = firestore.client()

# ------------------------
# Flask App Setup
# ------------------------
app = Flask(__name__)
app.secret_key = "supersecretkey"


# ------------------------
# Load .env file
# ------------------------
load_dotenv()
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")     # e.g. admin@gmail.com
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")




@app.route("/", methods=["GET"])
def index():
    """Show only Register and Login options."""
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        owner_name = request.form.get("owner_name")
        email = request.form.get("email").lower()
        company_name = request.form.get("company_name")
        company_address = request.form.get("company_address")
        phone_no = request.form.get("phone_no")
        company_gst = request.form.get("company_gst")
        password = request.form.get("password")

        # -----------------------------
        # CHECK EMAIL ALREADY EXISTS
        # -----------------------------
        existing = db.collection("users").where("email", "==", email).stream()
        if any(existing):
            flash("Email already registered!", "error")
            return redirect(url_for("register"))

        # -----------------------------
        # HANDLE LOGO UPLOAD → BASE64
        # -----------------------------
        import base64

        logo_file = request.files.get("logo")
        logo_base64 = None

        if logo_file:
            logo_base64 = base64.b64encode(logo_file.read()).decode("utf-8")

        # -----------------------------
        # SAVE USER TO FIRESTORE
        # -----------------------------
        db.collection("users").add({
            "owner_name": owner_name,
            "email": email,
            "company_name": company_name,
            "company_address": company_address,
            "phone_no": phone_no,
            "company_gst": company_gst,
            "password": generate_password_hash(password),
            "logo_base64": logo_base64   # <-- STORE BASE64 LOGO
        })

        flash("Registration successful! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        email = request.form.get("email").strip().lower()
        password = request.form.get("password").strip()



        # ----------------------------------------
        # ADMIN LOGIN CHECK
        # ----------------------------------------
        if email == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
            session["role"] = "admin"
            session["email"] = email
            flash("Admin login successful!", "success")
            return redirect(url_for("admin_dashboard"))

        # ----------------------------------------
        # USER LOGIN CHECK (FIRESTORE)
        # ----------------------------------------
        user_docs = db.collection("users").where("email", "==", email).stream()
        user = None
        for doc in user_docs:
            user = doc.to_dict()
            user["id"] = doc.id

        if not user:
            flash("Email not found!", "error")
            return redirect(url_for("login"))

        # Check user password (hashed)
        if not check_password_hash(user["password"], password):
            flash("Incorrect Password!", "error")
            return redirect(url_for("login"))

        # Save user session
        session["role"] = "user"
        session["user_id"] = user["id"]
        session["owner_name"] = user["owner_name"]

        flash("User login successful!", "success")
        return redirect(url_for("user_dashboard"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect(url_for("login"))


@app.route("/admin/dashboard", methods=["GET"])
def admin_dashboard():
    if session.get("role") != "admin":
        flash("Unauthorized Access!", "error")
        return redirect(url_for("login"))

    # Filters
    filter_company = request.args.get("company", "").strip().lower()
    filter_customer = request.args.get("customer", "").strip().lower()

    # Fetch all users (companies)
    user_docs = db.collection("users").stream()
    companies = {doc.id: doc.to_dict() for doc in user_docs}

    # Fetch all invoices
    invoice_docs = db.collection("invoices").stream()
    all_invoices = []

    for doc in invoice_docs:
        data = doc.to_dict()
        data["doc_id"] = doc.id
        all_invoices.append(data)

    # Apply Filters
    if filter_company:
        all_invoices = [
            inv for inv in all_invoices
            if companies.get(inv.get("created_by"), {})
                .get("company_name", "").lower().startswith(filter_company)
        ]

    if filter_customer:
        all_invoices = [
            inv for inv in all_invoices
            if inv.get("client_name", "").lower().startswith(filter_customer)
        ]

    # Group invoices company-wise
    grouped_data = {}
    for comp_id, comp in companies.items():
        grouped_data[comp_id] = {
            "company_name": comp.get("company_name", "(No Name)"),
            "sub_company": comp.get("owner_name", ""),
            "invoices": [
                inv for inv in all_invoices if inv.get("created_by") == comp_id
            ]
        }

    return render_template(
        "admin_dashboard.html",
        grouped_data=grouped_data,
        filter_company=filter_company,
        filter_customer=filter_customer
    )

@app.route("/admin/users")
def admin_users():
    if session.get("role") != "admin":
        flash("Unauthorized Access!", "error")
        return redirect(url_for("login"))

    # Fetch all users
    user_docs = db.collection("users").stream()
    users = []
    for doc in user_docs:
        data = doc.to_dict()
        data["user_id"] = doc.id
        users.append(data)

    return render_template("admin_users.html", users=users)


@app.route("/admin/update_user/<string:user_id>", methods=["POST"])
def admin_update_user(user_id):
    if session.get("role") != "admin":
        flash("Unauthorized Access!", "error")
        return redirect(url_for("login"))

    # Get updated fields
    owner_name = request.form.get("owner_name")
    email = request.form.get("email")
    company_name = request.form.get("company_name")
    company_address = request.form.get("company_address")
    phone_no = request.form.get("phone_no")
    company_gst = request.form.get("company_gst")

    # Handle logo upload
    import base64
    logo_file = request.files.get("logo")
    logo_base64 = None

    if logo_file and logo_file.filename != "":
        logo_base64 = base64.b64encode(logo_file.read()).decode("utf-8")

    update_data = {
        "owner_name": owner_name,
        "email": email,
        "company_name": company_name,
        "company_address": company_address,
        "phone_no": phone_no,
        "company_gst": company_gst,
    }

    # update only if new logo uploaded
    if logo_base64:
        update_data["logo_base64"] = logo_base64

    db.collection("users").document(user_id).update(update_data)

    flash("User profile updated successfully!", "success")
    return redirect(url_for("admin_users"))


@app.route("/user/dashboard", methods=["GET", "POST"])
def user_dashboard():
    if session.get("role") != "user":
        flash("Unauthorized Access!", "error")
        return redirect(url_for("login"))

    user_id = session.get("user_id")

    # -------------------------
    # FETCH FILTER INPUTS
    # -------------------------
    customer_name = request.args.get("customer_name", "").strip().lower()
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")

    # -------------------------
    # BASE QUERY
    # -------------------------
    invoice_query = db.collection("invoices").where("created_by", "==", user_id)

    # -------------------------
    # FILTER BY CUSTOMER NAME
    # -------------------------
    if customer_name:
        all_docs = invoice_query.stream()
        invoice_list = []
        for doc in all_docs:
            data = doc.to_dict()
            if customer_name in data.get("client_name", "").lower():
                data["doc_id"] = doc.id
                invoice_list.append(data)
    else:
        invoice_list = []
        for doc in invoice_query.stream():
            data = doc.to_dict()
            data["doc_id"] = doc.id
            invoice_list.append(data)

    # -------------------------
    # FILTER BY DATE RANGE
    # -------------------------
    def date_in_range(inv_date):
        if not inv_date:
            return False

        try:
            dt = datetime.strptime(inv_date, "%Y-%m-%d")
        except:
            return False

        if from_date:
            f_dt = datetime.strptime(from_date, "%Y-%m-%d")
            if dt < f_dt:
                return False

        if to_date:
            t_dt = datetime.strptime(to_date, "%Y-%m-%d")
            if dt > t_dt:
                return False

        return True

    if from_date or to_date:
        invoice_list = [inv for inv in invoice_list if date_in_range(inv.get("invoice_date"))]

    # -------------------------
    # DEPARTMENTS (WITH ID)
    # -------------------------
    dep_docs = db.collection("users").document(user_id).collection("departments").stream()

    departments = []
    for d in dep_docs:
        data = d.to_dict()
        data["dep_id"] = d.id            # IMPORTANT
        departments.append(data)

    total_departments = len(departments)
    total_invoices = len(invoice_list)

    # -------------------------
    # RETURN PAGE
    # -------------------------
    return render_template(
        "user_dashboard.html",
        invoices=invoice_list,
        departments=departments,  # FIXED
        total_departments=total_departments,
        total_invoices=total_invoices,
        customer_name=customer_name,
        from_date=from_date,
        to_date=to_date
    )


@app.route("/create_department", methods=["GET", "POST"])
def create_department():
    # Ensure only logged-in users can access
    if "user_id" not in session:
        flash("Please login first!", "error")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        department_name = request.form.get("department_name")
        sub_company_name = request.form.get("sub_company_name")

        # Save department inside user's department collection
        db.collection("users").document(user_id).collection("departments").add({
            "department_name": department_name,
            "sub_company_name": sub_company_name,
            "created_at": datetime.now(),
            "created_by": user_id
        })

        flash("Department Created Successfully!", "success")
        return redirect(url_for("user_dashboard"))

    return render_template("create_department.html")





@app.route("/create_invoice", methods=["GET", "POST"])
def create_invoice():
    if "user_id" not in session:
        flash("Please login first!", "error")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # ------------------------- POST (SAVE INVOICE) -------------------------
    if request.method == "POST":
        invoice_number = request.form.get("invoice_no")
        invoice_date = request.form.get("invoice_date")
        due_date = request.form.get("due_date")

        client_name = request.form.get("client_name")
        client_email = request.form.get("client_email")
        client_po = request.form.get("client_po")
        client_address = request.form.get("client_address")
        client_phone = request.form.get("client_phone")

        departments = request.form.getlist("departments")
        taxes = request.form.getlist("taxes")
        notes = request.form.get("notes")

        item_names = request.form.getlist("item_name[]")
        quantities = request.form.getlist("quantity[]")
        unit_prices = request.form.getlist("unit_price[]")
        totals = request.form.getlist("total[]")

        line_items = []
        for i in range(len(item_names)):
            line_items.append({
                "item_name": item_names[i],
                "quantity": int(quantities[i]),
                "unit_price": float(unit_prices[i]),
                "total": float(totals[i])
            })

        subtotal = float(request.form.get("subtotal"))
        gst_amount = float(request.form.get("gst_amount"))
        final_total = float(request.form.get("final_total"))

        db.collection("invoices").add({
            "invoice_no": invoice_number,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "client_name": client_name,
            "client_email": client_email,
            "client_po": client_po,
            "client_phone": client_phone,
            "client_address": client_address,
            "departments": departments,
            "taxes": taxes,
            "notes": notes,
            "items": line_items,
            "subtotal": subtotal,
            "gst_amount": gst_amount,
            "final_total": final_total,
            "created_by": user_id,
            "created_at": datetime.now()
        })

        flash("Invoice Created Successfully!", "success")
        return redirect(url_for("user_dashboard"))

    # ------------------------- GET (LOAD PAGE) -------------------------

    dep_docs = db.collection("users").document(user_id).collection("departments").stream()
    dynamic_departments = [doc.to_dict().get("department_name") for doc in dep_docs]

    # When loading page, invoice_no is blank → user must select department first
    return render_template(
        "create_invoice.html",
        departments=dynamic_departments,
        invoice_no=""
    )


@app.route("/generate_invoice_no", methods=["POST"])
def generate_invoice_no():
    if "user_id" not in session:
        return {"error": "Unauthorized"}, 401

    user_id = session["user_id"]
    data = request.get_json()
    selected_dep = data.get("department")

    if not selected_dep:
        return {"error": "No department selected"}, 400

    # Fetch user details
    user_data = db.collection("users").document(user_id).get().to_dict()
    company_name = user_data.get("company_name", "")
    company_prefix = company_name.replace(" ", "")[:3].upper()

    # Department prefix
    dep_prefix = selected_dep.replace(" ", "")[:3].upper()

    # Fetch all invoices for this user
    invoice_docs = db.collection("invoices") \
        .where("created_by", "==", user_id) \
        .stream()

    last_serial = 0

    for doc in invoice_docs:
        inv = doc.to_dict()
        if selected_dep in inv.get("departments", []):
            try:
                serial = int(inv["invoice_no"][-3:])
                if serial > last_serial:
                    last_serial = serial
            except:
                pass

    new_serial = str(last_serial + 1).zfill(3)

    invoice_no = f"{company_prefix}-{dep_prefix}-{new_serial}"

    return {"invoice_no": invoice_no}, 200


@app.route("/invoice/<doc_id>")
def view_invoice(doc_id):
    # Fetch invoice
    doc = db.collection("invoices").document(doc_id).get()
    if not doc.exists:
        flash("Invoice not found!", "error")
        return redirect(url_for("user_dashboard"))

    invoice = doc.to_dict()
    invoice["doc_id"] = doc.id

    # Ensure items list exists
    if "items" not in invoice or not isinstance(invoice["items"], list):
        invoice["items"] = []

    # Fetch logged-in user details (company info)
    user_id = invoice.get("created_by")
    user_doc = db.collection("users").document(user_id).get()

    if user_doc.exists:
        user_data = user_doc.to_dict()
    else:
        user_data = {}

    # ---------------------------
    # DETERMINE SUB-COMPANY
    # ---------------------------
    selected_departments = invoice.get("departments", [])
    sub_company_name = None

    dep_docs = db.collection("users").document(user_id).collection("departments").stream()
    for dep in dep_docs:
        dep_data = dep.to_dict()
        if dep_data.get("department_name") in selected_departments:
            sub_company_name = dep_data.get("sub_company_name")
            break

    # If no sub-company → fallback to main company
    final_company_name = (
        sub_company_name if sub_company_name else user_data.get("company_name", "Company")
    )

    # ---------------------------
    # PREPARE COMPANY INFO
    # ---------------------------
    company = {
        "company_name": final_company_name,
        "owner_name": user_data.get("owner_name", ""),
        "address": user_data.get("company_address", ""),
        "gst_no": user_data.get("company_gst", ""),
        "email": user_data.get("email", ""),
        "phone_no": user_data.get("phone_no", "Not Provided")
    }

    return render_template("view_invoice.html", invoice=invoice, company=company)
@app.route("/invoice/<string:doc_id>/edit", methods=["GET", "POST"])
def edit_invoice(doc_id):
    if "user_id" not in session:
        flash("Please login first!", "error")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    doc_ref = db.collection("invoices").document(doc_id)
    invoice_doc = doc_ref.get()

    if not invoice_doc.exists:
        flash("Invoice not found!", "error")
        return redirect(url_for("user_dashboard"))

    old_invoice = invoice_doc.to_dict()

    # ---------------- POST: SAVE UPDATED DATA ----------------
    if request.method == "POST":

        updated_data = {
            "invoice_no": request.form.get("invoice_no"),
            "invoice_date": request.form.get("invoice_date"),
            "due_date": request.form.get("due_date"),

            "client_name": request.form.get("client_name"),
            "client_email": request.form.get("client_email"),
            "client_po": request.form.get("client_po"),
            "client_address": request.form.get("client_address"),

            "departments": request.form.getlist("departments"),
            "taxes": request.form.getlist("taxes"),
            "notes": request.form.get("notes"),

            "subtotal": float(request.form.get("subtotal")),
            "gst_amount": float(request.form.get("gst_amount")),
            "final_total": float(request.form.get("final_total")),
            "updated_at": datetime.now()
        }

        # ---------------- LINE ITEMS ----------------
        item_names = request.form.getlist("item_name[]")
        quantities = request.form.getlist("quantity[]")
        unit_prices = request.form.getlist("unit_price[]")
        totals = request.form.getlist("total[]")

        line_items = []
        for i in range(len(item_names)):
            line_items.append({
                "item_name": item_names[i],
                "quantity": int(quantities[i]),
                "unit_price": float(unit_prices[i]),
                "total": float(totals[i])
            })

        updated_data["items"] = line_items

        doc_ref.update(updated_data)

        flash("Invoice Updated Successfully!", "success")
        return redirect(url_for("user_dashboard"))

    # ---------------- GET REQUEST ----------------
    # Fetch departments
    dep_docs = db.collection("users").document(user_id).collection("departments").stream()
    dynamic_departments = [d.to_dict().get("department_name") for d in dep_docs]

    return render_template(
        "edit_invoice.html",
        invoice=old_invoice,
        doc_id=doc_id,
        departments=dynamic_departments
    )



@app.route("/delete_invoice/<string:doc_id>", methods=["POST"])
def delete_invoice(doc_id):
    if "user_id" not in session:
        flash("Please login first!", "error")
        return redirect(url_for("login"))

    try:
        db.collection("invoices").document(doc_id).delete()
        flash("Invoice deleted successfully!", "success")
    except:
        flash("Failed to delete invoice!", "error")

    return redirect(url_for("user_dashboard"))

@app.route("/delete_department/<string:dep_id>", methods=["POST"])
def delete_department(dep_id):
    if "user_id" not in session:
        flash("Please login first!", "error")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    try:
        db.collection("users").document(user_id).collection("departments").document(dep_id).delete()
        flash("Department deleted successfully!", "success")
    except:
        flash("Failed to delete department!", "error")

    return redirect(url_for("user_dashboard"))






@app.route("/invoice/<string:doc_id>/download_pdf")
def download_invoice_pdf(doc_id):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    import base64

    # ---------- GENERIC WRAP ----------
    def wrap_text(canvas_obj, text, x, y, max_width, font="Helvetica", font_size=11, line_height=14, center=False):
        canvas_obj.setFont(font, font_size)
        words = text.split()
        line = ""
        for word in words:
            test = (line + " " + word).strip()
            if canvas_obj.stringWidth(test, font, font_size) <= max_width:
                line = test
            else:
                if center:
                    canvas_obj.drawCentredString(x, y, line)
                else:
                    canvas_obj.drawString(x, y, line)
                y -= line_height
                line = word

        if line:
            if center:
                canvas_obj.drawCentredString(x, y, line)
            else:
                canvas_obj.drawString(x, y, line)
        return y

    # ---------- FETCH ----------
    doc_ref = db.collection("invoices").document(doc_id).get()
    if not doc_ref.exists:
        return "Invoice not found", 404

    invoice = doc_ref.to_dict()
    user_id = invoice.get("created_by")
    user = db.collection("users").document(user_id).get().to_dict()

    # *************** UPDATED COMPANY NAME ***************
    selected_departments = invoice.get("departments", [])
    sub_company_name = None

    dep_docs = db.collection("users").document(user_id).collection("departments").stream()
    for dep in dep_docs:
        dep_data = dep.to_dict()
        if dep_data.get("department_name") in selected_departments:
            sub_company_name = dep_data.get("sub_company_name")
            break

    # FIXED: fallback variable was wrong before
    final_company_name = (
        sub_company_name if sub_company_name else user.get("company_name", "Company")
    )
    # ****************************************************

    company_address = user.get("company_address", "")
    company_email = user.get("email", "")
    company_phone = user.get("phone_no", "")
    owner_name = user.get("owner_name", "")
    company_gst = user.get("company_gst", "")
    logo_base64 = user.get("logo_base64")

    # ---------- PDF SETUP ----------
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4

    # ---------- WATERMARK ----------
    if logo_base64:
        try:
            img = ImageReader(io.BytesIO(base64.b64decode(logo_base64)))
            c.saveState()
            c.setFillAlpha(0.06)
            c.drawImage(img, (width - 280) / 2, (height - 280) / 2, width=280, height=280, mask="auto")
            c.restoreState()
        except:
            pass

    # ---------- LOGO ON TOP ----------
    if logo_base64:
        try:
            c.drawImage(ImageReader(io.BytesIO(base64.b64decode(logo_base64))),
                        width / 2 - 40, height - 110,
                        width=80, height=80,
                        preserveAspectRatio=True, mask="auto")
        except:
            pass

    # ---------- COMPANY NAME ----------
    y_name = height - 145

    # FIXED: previously used undefined variable company_name
    y_name = wrap_text(c, final_company_name, width / 2, y_name,
                       max_width=350, font="Helvetica-Bold",
                       font_size=18, center=True, line_height=22)

    # ---------- COMPANY ADDRESS ----------
    y_name = wrap_text(c, company_address, width / 2, y_name - 15,
                       max_width=380, font="Helvetica", font_size=11, center=True)

    c.drawCentredString(width / 2, y_name - 15, f"Email: {company_email} | Phone: {company_phone}")

    # ---------- INVOICE DETAILS ----------
    y = height - 240
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, "Invoice Details:")
    c.setFont("Helvetica", 11)
    c.drawString(60, y - 20, f"Invoice No: {invoice.get('invoice_no')}")
    c.drawString(60, y - 35, f"Invoice Date: {invoice.get('invoice_date')}")
    c.drawString(60, y - 50, f"Due Date: {invoice.get('due_date')}")
    c.drawString(60, y - 65, f"GSTIN: {company_gst}")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(390, y - 60, "Customer Details:")

    c.setFont("Helvetica", 11)
    start_y = y - 75

    wrapped_end_y = wrap_text(
        c,
        "Name: " + (invoice.get("client_name") or ""),
        390,
        start_y,
        max_width=160,
        font="Helvetica",
        font_size=11
    )

    email_y = wrapped_end_y - 15
    phone_y = email_y - 15
    phone_p = phone_y - 15
    address_y = phone_p - 15
    
    c.drawString(390, email_y, f"Email: {invoice.get('client_email')}")
    c.drawString(390, phone_p, f"Phone: {invoice.get('client_phone')}")
    c.drawString(390, phone_y, f"Purchase-order: {invoice.get('client_po')}")

    wrap_text(
        c,
        "Address: " + (invoice.get("client_address") or ""),
        390,
        address_y,
        max_width=160,
        font="Helvetica",
        font_size=11
    )

    # ---------- TABLE ----------
    data = [["Item/Service", "Qty", "Unit Price", "Total"]]

    for item in invoice.get("items", []):
        data.append([
            item.get("item_name", ""),
            item.get("quantity", ""),
            f"{item.get('unit_price', 0):.2f}",
            f"{item.get('total', 0):.2f}"
        ])

    table = Table(data, colWidths=[220, 70, 120, 120])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
    ]))

    y_table = y - 180
    table.wrapOn(c, width, height)
    table.drawOn(c, 40, y_table - len(data) * 20)

    y_tot = y_table - len(data) * 20 - 40

    c.drawRightString(450, y_tot, "Subtotal:")
    c.drawRightString(550, y_tot, f"Rs. {invoice.get('subtotal', 0):.2f}")

    c.drawRightString(450, y_tot - 18, "GST:")
    c.drawRightString(550, y_tot - 18, f"Rs. {invoice.get('gst_amount', 0):.2f}")

    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(450, y_tot - 38, "Final Total:")
    c.drawRightString(550, y_tot - 38, f"Rs. {invoice.get('final_total', 0):.2f}")

    c.setFont("Helvetica-Oblique", 11)
    c.drawRightString(550, y_tot - 85, "Signature & Stamp")
    c.drawRightString(550, y_tot - 100, owner_name)

    c.save()
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"{invoice.get('invoice_no')}.pdf",
        mimetype="application/pdf"
    )



# from sendgrid import SendGridAPIClient
# from sendgrid.helpers.mail import Mail, Attachment, Content
# from sendgrid.helpers.mail import Disposition, FileContent, FileName, FileType,Email
#
# def send_invoice_email(company_email, to_email, subject, body, pdf_bytes):
#     """
#     Send invoice using SendGrid with PDF attachment + branded footer.
#     Reply-to = company email
#     """
#
#     sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
#     sender_email = os.getenv("SENDGRID_SENDER")
#
#     if not sendgrid_api_key:
#         raise Exception("SENDGRID_API_KEY missing in .env file")
#
#     if not sender_email:
#         raise Exception("SENDGRID_SENDER missing in .env file")
#
#     # Convert PDF to base64
#     encoded_pdf = base64.b64encode(pdf_bytes).decode()
#
#     # Add branding + footer
#     body = (
#         body
#         + "\n\n----------------------------------------\n"
#         + "🏢 *Powered by KITS Invoice System*\n"
#         + "----------------------------------------"
#     )
#
#     # Create message
#     message = Mail(
#         from_email=Email(sender_email),
#         to_emails=Email(to_email),
#         subject=subject,
#         plain_text_content=body
#     )
#
#     # Set reply-to (dynamic)
#     message.reply_to = Email(company_email)
#
#     # Prepare attachment
#     attachment = Attachment(
#         file_content=FileContent(encoded_pdf),
#         file_type=FileType("application/pdf"),
#         file_name=FileName("invoice.pdf"),
#         disposition=Disposition("attachment")
#     )
#
#     # Add attachment
#     message.add_attachment(attachment)
#
#     # Send email
#     try:
#         sg = SendGridAPIClient(sendgrid_api_key)
#         response = sg.send(message)
#         print("SENDGRID STATUS:", response.status_code)
#         print(response.body)
#         print(response.headers)
#     except Exception as e:
#         print("SENDGRID ERROR:", e)
#         raise e
#
# @app.route("/send_invoice/<string:doc_id>", methods=["POST"])
# def send_invoice(doc_id):
#     from reportlab.platypus import Table, TableStyle
#     from reportlab.lib import colors
#     from reportlab.lib.utils import ImageReader
#     import base64
#
#     if "user_id" not in session:
#         return "Unauthorized", 403
#
#     # Fetch invoice
#     doc_ref = db.collection("invoices").document(doc_id).get()
#     if not doc_ref.exists:
#         flash("Invoice not found!", "error")
#         return redirect(url_for("user_dashboard"))
#
#     invoice = doc_ref.to_dict()
#
#     # Fetch company user
#     user_doc = db.collection("users").document(invoice["created_by"]).get()
#     user = user_doc.to_dict()
#
#     # -------------------------------------------
#     # EMAILS
#     # -------------------------------------------
#     company_email = user.get("email")            # reply-to
#     customer_email = invoice.get("client_email") # receiver
#
#     # -------------------------------------------
#     # START PDF CREATION (Same Format As Download)
#     # -------------------------------------------
#
#     def wrap_text(canvas_obj, text, x, y, max_width, font="Helvetica", font_size=11, line_height=14, center=False):
#         canvas_obj.setFont(font, font_size)
#         words = text.split()
#         line = ""
#         for word in words:
#             test = (line + " " + word).strip()
#             if canvas_obj.stringWidth(test, font, font_size) <= max_width:
#                 line = test
#             else:
#                 if center:
#                     canvas_obj.drawCentredString(x, y, line)
#                 else:
#                     canvas_obj.drawString(x, y, line)
#                 y -= line_height
#                 line = word
#         if line:
#             if center:
#                 canvas_obj.drawCentredString(x, y, line)
#             else:
#                 canvas_obj.drawString(x, y, line)
#         return y
#
#     # Company info
#     company_name = user.get("company_name", "")
#     company_address = user.get("company_address", "")
#     company_phone = user.get("phone_no", "")
#     owner_name = user.get("owner_name", "")
#     company_gst = user.get("company_gst", "")
#     logo_base64 = user.get("logo_base64")
#
#     # Setup PDF
#     pdf_buffer = io.BytesIO()
#     c = canvas.Canvas(pdf_buffer, pagesize=A4)
#     width, height = A4
#
#     # Watermark
#     if logo_base64:
#         try:
#             img = ImageReader(io.BytesIO(base64.b64decode(logo_base64)))
#             c.saveState()
#             c.setFillAlpha(0.06)
#             c.drawImage(img, (width - 280) / 2, (height - 280) / 2,
#                         width=280, height=280, mask="auto")
#             c.restoreState()
#         except:
#             pass
#
#     # Logo on top
#     if logo_base64:
#         try:
#             c.drawImage(
#                 ImageReader(io.BytesIO(base64.b64decode(logo_base64))),
#                 width / 2 - 40, height - 110,
#                 width=80, height=80,
#                 preserveAspectRatio=True,
#                 mask="auto"
#             )
#         except:
#             pass
#
#     # Responsive Company Name
#     y_name = height - 145
#     y_name = wrap_text(c, company_name, width / 2, y_name,
#                        max_width=350, font="Helvetica-Bold", font_size=18,
#                        center=True, line_height=22)
#
#     y_name = wrap_text(
#         c, company_address, width / 2, y_name - 15,
#         max_width=380, font="Helvetica", font_size=11, center=True
#     )
#
#     c.drawCentredString(width / 2, y_name - 15,
#                         f"Email: {company_email} | Phone: {company_phone}")
#
#     # Invoice Details
#     y = height - 240
#
#     c.setFont("Helvetica-Bold", 12)
#     c.drawString(60, y, "Invoice Details:")
#     c.setFont("Helvetica", 11)
#     c.drawString(60, y - 20, f"Invoice No: {invoice['invoice_no']}")
#     c.drawString(60, y - 35, f"Invoice Date: {invoice['invoice_date']}")
#     c.drawString(60, y - 50, f"Due Date: {invoice['due_date']}")
#     c.drawString(60, y - 65, f"GSTIN: {company_gst}")
#
#     # Customer Details
#     c.setFont("Helvetica-Bold", 12)
#     c.drawString(390, y - 60, "Customer Details:")
#     c.setFont("Helvetica", 11)
#
#     start_y = y - 75
#     wrapped_end_y = wrap_text(
#         c, "Name: " + (invoice.get("client_name") or ""),
#         390, start_y, max_width=160
#     )
#
#     email_y = wrapped_end_y - 15
#     phone_y = email_y - 15
#     addr_y = phone_y - 20
#
#     c.drawString(390, email_y, f"Email: {invoice.get('client_email')}")
#     c.drawString(390, phone_y, f"Purches-order: {invoice.get('client_po')}")
#
#     wrap_text(
#         c, "Address: " + (invoice.get("client_address") or ""),
#         390, addr_y, max_width=160
#     )
#
#     # Table
#     data = [["Item/Service", "Qty", "Unit Price", "Total"]]
#     for item in invoice["items"]:
#         data.append([
#             item.get("item_name", ""),
#             item.get("quantity", ""),
#             f"{item.get('unit_price', 0):.2f}",
#             f"{item.get('total', 0):.2f}"
#         ])
#
#     table = Table(data, colWidths=[220, 70, 120, 120])
#     table.setStyle(TableStyle([
#         ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
#         ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
#         ("ALIGN", (1, 1), (-1, -1), "CENTER"),
#     ]))
#
#     y_table = y - 180
#     table.wrapOn(c, width, height)
#     table.drawOn(c, 40, y_table - len(data) * 20)
#
#     # Totals
#     y_tot = y_table - len(data) * 20 - 40
#     c.drawRightString(450, y_tot, "Subtotal:")
#     c.drawRightString(550, y_tot, f"Rs. {invoice['subtotal']:.2f}")
#
#     c.drawRightString(450, y_tot - 18, "GST:")
#     c.drawRightString(550, y_tot - 18, f"Rs. {invoice['gst_amount']:.2f}")
#
#     c.setFont("Helvetica-Bold", 12)
#     c.drawRightString(450, y_tot - 38, "Final Total:")
#     c.drawRightString(550, y_tot - 38, f"Rs. {invoice['final_total']:.2f}")
#
#     # Signature
#     c.setFont("Helvetica-Oblique", 11)
#     c.drawRightString(550, y_tot - 85, "Signature & Stamp")
#     c.drawRightString(550, y_tot - 100, owner_name)
#
#     c.save()
#     pdf_buffer.seek(0)
#     pdf_bytes = pdf_buffer.getvalue()
#
#     # --------------------------------------------------
#     # SEND USING SENDGRID (Your working function)
#     # --------------------------------------------------
#     try:
#         send_invoice_email(
#             company_email,      # reply-to
#             customer_email,     # receiver
#             f"Invoice #{invoice['invoice_no']}",
#             "Dear Customer,\n\nYour invoice is attached.\n\nThank you!",
#             pdf_bytes
#         )
#         flash("Invoice sent successfully using SendGrid!", "success")
#
#     except Exception as e:
#         flash(f"Failed to send email: {str(e)}", "error")
#
#     return redirect(url_for("user_dashboard"))
#
#

# ------------------------
# Run App
# ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)

