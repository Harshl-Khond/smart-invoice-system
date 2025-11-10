from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import datetime, timedelta
import io
import os
import firebase_admin
from firebase_admin import credentials, firestore

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
# Static credentials (login)
# ------------------------
USERNAME = "kitstechlearning.co.in"
PASSWORD = "kits@9876"

# ------------------------
# Routes
# ------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    """Simple static login."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == USERNAME and password == PASSWORD:
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password!", "error")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/index", methods=["GET"])
def index():
    """Show all invoices from Firestore."""
    invoices_ref = db.collection("invoices").stream()
    invoices = [doc.to_dict() | {"doc_id": doc.id} for doc in invoices_ref]

    search_query = request.args.get("search", "").strip().lower()
    if search_query:
        invoices = [
            inv for inv in invoices
            if search_query in inv.get("client_name", "").lower()
            or search_query in str(inv.get("invoice_no", "")).lower()
        ]

    return render_template("index.html", invoices=invoices, search_query=search_query)


# 🔹 Department short codes for invoice prefixes
DEPARTMENT_CODES = {
    "robotics": "ROB",
    "it_arvr": "IT",
    "3dprinting": "3DP"
}


@app.route("/create", methods=["GET", "POST"])
def create_invoice():
    """Create a new invoice and store it in Firestore."""
    if request.method == "POST":
        client_name = request.form["client_name"]
        client_email = request.form.get("client_email", "")
        client_phone = request.form.get("client_phone", "")
        client_address = request.form.get("client_address", "")
        description = request.form.get("description", "")
        invoice_date = request.form.get("invoice_date", datetime.now().strftime("%Y-%m-%d"))
        due_date = request.form.get("due_date", (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"))

        # ✅ Get selected departments
        selected_departments = request.form.getlist("departments")
        if not selected_departments:
            flash("Please select at least one department.", "danger")
            return redirect(url_for("create_invoice"))

        # ✅ Generate Invoice ID
        first_dept = selected_departments[0]
        dept_code = DEPARTMENT_CODES.get(first_dept, "GEN")
        invoices = db.collection("invoices").where("department_code", "==", dept_code).stream()
        count = sum(1 for _ in invoices)
        next_number = str(count + 1).zfill(3)
        invoice_no = f"KITS-{dept_code}-{next_number}"

        # Collect items
        service_names = request.form.getlist("service_name[]")
        quantities = request.form.getlist("quantity[]")
        amounts = request.form.getlist("amount[]")
        items = []
        subtotal = 0
        for s, q, a in zip(service_names, quantities, amounts):
            try:
                q = int(q)
                a = float(a)
                total = q * a
                items.append({
                    "service_name": s,
                    "quantity": q,
                    "amount": a,
                    "total": total
                })
                subtotal += total
            except ValueError:
                continue

        # ✅ GST Calculation based on checkboxes
        cgst = request.form.get("cgst")
        sgst = request.form.get("sgst")
        gst_rate = 0
        if cgst and sgst:
            gst_rate = 18
        elif cgst or sgst:
            gst_rate = 9

        gst_amount = round((subtotal * gst_rate) / 100, 2)
        final_total = round(subtotal + gst_amount, 2)

        invoice_data = {
            "invoice_no": invoice_no,
            "client_name": client_name,
            "client_email": client_email,
            "client_phone": client_phone,
            "client_address": client_address,
            "description": description,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "items": items,
            "subtotal": subtotal,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "final_total": final_total,
            "created_at": datetime.now().isoformat(),
            "departments": selected_departments,
            "department_code": dept_code
        }

        # Store in Firestore
        doc_ref = db.collection("invoices").add(invoice_data)
        doc_id = doc_ref[1].id

        flash(f"Invoice {invoice_no} created successfully!", "success")
        return redirect(url_for("view_invoice", doc_id=doc_id))

    return render_template("create_invoice.html")



@app.route("/invoice/<string:doc_id>")
def view_invoice(doc_id):
    """View a single invoice from Firestore with full company and customer details."""
    doc_ref = db.collection("invoices").document(doc_id).get()
    if not doc_ref.exists:
        return "Invoice not found", 404

    invoice = doc_ref.to_dict()
    invoice["id"] = doc_id

    # Determine company name based on selected department
    dept_names = invoice.get("departments", [])
    company_name = "KAJAL INNOVATION AND TECHNICAL SOLUTIONS"
    if "it_arvr" in dept_names:
        company_name = "KITS Software Solution Pvt Ltd"
    elif "robotics" in dept_names:
        company_name = "KITS Robotics and Automation Pvt Ltd"
    elif "3dprinting" in dept_names:
        company_name = "KITS 3D Printing Pvt Ltd"

    # Determine GST type applied
    gst_type = "None"
    if invoice.get("gst_rate", 0) == 18:
        gst_type = "CGST + SGST"
    elif invoice.get("gst_rate", 0) == 9:
        gst_type = "CGST or SGST"

    company_info = {
        "name": company_name,
        "address": "KITS, 1st floor, Mukta Plaza, KITS Square, Income tax chowk, AKOLA",
        "email": "info@kitstechlearning.co.in",
        "phone": "9226983129 / 7385582242",
        "website": "www.kitstechlearning.co.in",
        "logo": "company_logo.jpg",
        "gst_type": gst_type
    }

    return render_template("view_invoice.html", invoice=invoice, company=company_info)


@app.route("/delete/<doc_id>", methods=["POST"])
def delete_invoice(doc_id):
    try:
        # Reference to the document
        invoice_ref = db.collection("invoices").document(doc_id)

        # Check if it exists before deleting
        if invoice_ref.get().exists:
            invoice_ref.delete()
            flash("✅ Invoice deleted successfully!", "success")
        else:
            flash("⚠️ Invoice not found in Firestore.", "warning")

    except Exception as e:
        flash(f"❌ Error deleting invoice: {e}", "error")

    return redirect(url_for("index"))



@app.route("/invoice/<string:doc_id>/download_pdf")
def download_invoice_pdf(doc_id):
    """Generate dynamic PDF invoice with logo watermark (behind content) from Firestore."""
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    # 🔹 Fetch invoice from Firestore
    doc_ref = db.collection("invoices").document(doc_id).get()
    if not doc_ref.exists:
        return "Invoice not found", 404

    invoice = doc_ref.to_dict()

    # Create PDF in memory
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)
    width, height = A4

    # 🔹 Company details
    departments = invoice.get("departments", [])
    company_name = "KITS Innovation and Technical Solutions Pvt Ltd"
    if "it_arvr" in departments:
        company_name = "KITS Software Solution Pvt Ltd"
    elif "robotics" in departments:
        company_name = "KITS Robotics and Automation Pvt Ltd"
    elif "3dprinting" in departments:
        company_name = "KITS 3D Printing Pvt Ltd"

    company_address = "KITS, 1st Floor, Mukta Plaza, KITS Square, Income Tax Chowk, Akola"
    company_email = "info@kitstechlearning.co.in"
    company_phone = "9226983129 / 7385582242"
    company_website = "www.kitstechlearning.co.in"
    company_logo_path = os.path.join("static", "company_logo.jpg")

    # 🔹 Add faded background logo watermark
    if os.path.exists(company_logo_path):
        watermark_w, watermark_h = 300, 300
        c.saveState()
        c.setFillAlpha(0.08)  # Transparency for watermark (0.0 = fully transparent, 1.0 = solid)
        c.drawImage(
            company_logo_path,
            (width - watermark_w) / 2,
            (height - watermark_h) / 2,
            width=watermark_w,
            height=watermark_h,
            mask="auto"
        )
        c.restoreState()

    # 🔹 Company Logo (top)
    if os.path.exists(company_logo_path):
        logo_w, logo_h = 100, 100
        c.drawImage(company_logo_path, (width - logo_w) / 2, height - 130, width=logo_w, height=logo_h, mask="auto")

    # Header
    c.setFont("Helvetica-Bold", 18)
    c.setFillColorRGB(0.0, 0.3, 0.3)
    c.drawCentredString(width / 2, height - 150, company_name)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, height - 165, company_address)
    c.drawCentredString(width / 2, height - 180, f"Email: {company_email} | Phone: {company_phone}")
    c.drawCentredString(width / 2, height - 195, f"Website: {company_website}")

    # Invoice + Client Info
    y_pos = height - 230
    c.setFont("Helvetica-Bold", 12)
    c.drawString(80, y_pos, "Invoice Details:")
    c.setFont("Helvetica", 11)
    c.drawString(80, y_pos - 20, f"Invoice ID: {invoice.get('invoice_no', 'N/A')}")
    c.drawString(80, y_pos - 35, f"Invoice Date: {invoice.get('invoice_date', 'N/A')}")
    c.drawString(80, y_pos - 50, f"Due Date: {invoice.get('due_date', 'N/A')}")
    c.drawString(80, y_pos - 65, f"Description: {invoice.get('description', 'N/A')}")

    c.setFont("Helvetica-Bold", 12)
    c.drawString(360, y_pos - 75, "Client Details:")
    c.setFont("Helvetica", 11)
    c.drawString(360, y_pos - 95, f"Name: {invoice.get('client_name', 'N/A')}")
    c.drawString(360, y_pos - 110, f"Email: {invoice.get('client_email', 'N/A')}")
    c.drawString(360, y_pos - 125, f"Phone: {invoice.get('client_phone', 'N/A')}")
    c.drawString(360, y_pos - 140, f"Address: {invoice.get('client_address', 'N/A')}")


    # Table Data
    data = [["Service/Product", "Qty", "Unit Price (Rs.)", "Total (Rs.)"]]
    for item in invoice.get("items", []):
        data.append([
            item.get("service_name", ""),
            str(item.get("quantity", "")),
            f"Rs.{item.get('amount', 0):.2f}",
            f"Rs.{item.get('total', 0):.2f}",
        ])

    # Table styling
    table = Table(data, colWidths=[220, 80, 100, 100])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))

    # Dynamically position table (avoid overlap)
    y_table = height - 420
    available_height = y_table - 150
    row_height = 18
    table_height = len(data) * row_height

    if table_height > available_height:
        # Handle large tables: split across pages
        chunk_size = int(available_height // row_height)
        for start in range(0, len(data), chunk_size):
            chunk = data[start:start + chunk_size]
            t = Table(chunk, colWidths=[220, 80, 100, 100])
            t.setStyle(table._argW)
            t.wrapOn(c, width, height)
            t.drawOn(c, 50, y_table - (row_height * len(chunk)))
            c.showPage()

            # Add watermark (logo) again on new page background
            if os.path.exists(company_logo_path):
                c.saveState()
                c.setFillAlpha(0.08)
                c.drawImage(
                    company_logo_path,
                    (width - watermark_w) / 2,
                    (height - watermark_h) / 2,
                    width=watermark_w,
                    height=watermark_h,
                    mask="auto"
                )
                c.restoreState()
    else:
        table.wrapOn(c, width, height)
        table.drawOn(c, 50, y_table - table_height)

    # Totals Section (below table)
    y_total = y_table - table_height - 40
    c.setFont("Helvetica", 11)
    c.drawRightString(450, y_total, "Subtotal:")
    c.drawRightString(550, y_total, f"Rs.{invoice.get('subtotal', 0):.2f}")
    c.drawRightString(450, y_total - 15, f"GST ({invoice.get('gst_rate', 0)}%):")
    c.drawRightString(550, y_total - 15, f"Rs.{invoice.get('gst_amount', 0):.2f}")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(450, y_total - 35, "Final Total:")
    c.drawRightString(550, y_total - 35, f"Rs.{invoice.get('final_total', 0):.2f}")

    # Signature
    y_sign = y_total - 80
    c.setFont("Helvetica-Oblique", 11)
    c.drawRightString(525, y_sign, "Signature And Stamp")
    c.drawRightString(525, y_sign - 15, "Mis. Kajal Rajvaidya")
    c.drawRightString(530, y_sign - 30, "(CEO & Founder)")
    c.drawRightString(525, y_sign - 70, "--------------------")

    # Footer
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawCentredString(width / 2, 40, "Thank you for your business!")

    c.save()
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"invoice_{invoice.get('invoice_no', 'invoice')}.pdf",
        mimetype="application/pdf"
    )

# ------------------------
# Run App
# ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
