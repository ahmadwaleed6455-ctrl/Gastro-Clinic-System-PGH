import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from google.oauth2 import service_account
from google.cloud import firestore
import streamlit.components.v1 as components

# Set page config
st.set_page_config(page_title="Gastro Dr. Naveed Anwar - Clinic Portal", layout="wide")

# ----------------------------------------------------
# 🔐 FIREBASE CONNECTION
# ----------------------------------------------------
@st.cache_resource
def get_firestore_client():
    key_dict = dict(st.secrets["textkey"])
    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict["project_id"])

db = get_firestore_client()
log_ref = db.collection("patient_log")
settings_ref = db.collection("clinic_settings")

# ----------------------------------------------------
# ⚙️ DYNAMIC PRICING ENGINE
# ----------------------------------------------------
def get_clinic_fees():
    defaults = {
        "appt_fee": 2500.0,
        "None (Consultation Only)": 0.0,
        "OGD": 5000.0,
        "Limit Colonoscopy": 6000.0,
        "Colonoscopy": 9000.0,
        "ERCP": 25000.0,
        "PEG Tube": 15000.0
    }
    doc = settings_ref.document("pricing").get()
    if doc.exists:
        return doc.to_dict()
    else:
        settings_ref.document("pricing").set(defaults)
        return defaults

FEES = get_clinic_fees()
APPT_FEE = FEES.get("appt_fee", 2500.0)
PROCEDURE_FEES = {k: v for k, v in FEES.items() if k != "appt_fee"}

# ----------------------------------------------------
# 🕒 TIME & AUTO-RECEIPT GENERATOR
# ----------------------------------------------------
current_date_str = datetime.now().strftime("%Y-%m-%d")
display_datetime_form = datetime.now().strftime("%d-%m-%Y %I:%M %p")
receipt_date_suffix = datetime.now().strftime("%d%m%Y")

def generate_receipt_number():
    docs = log_ref.where("date", "==", current_date_str).stream()
    count = sum(1 for _ in docs)
    return f"GNA{receipt_date_suffix}{count + 1}"

auto_receipt_no = generate_receipt_number()

# ----------------------------------------------------
# 📊 SIDEBAR LIVE METRIC (NEW)
# ----------------------------------------------------
try:
    all_docs = log_ref.stream()
    all_data = [doc.to_dict() for doc in all_docs]
    if all_data:
        df_sidebar = pd.DataFrame(all_data)
        total_outstanding_balance = float(df_sidebar.get('balance', pd.Series()).sum())
    else:
        total_outstanding_balance = 0.0
except Exception:
    total_outstanding_balance = 0.0

st.sidebar.markdown("### 💳 Clinic Financial Status")
st.sidebar.metric("Total Outstanding Balance", f"Rs. {total_outstanding_balance:,.0f}")
st.sidebar.markdown("---")

# 🧭 MULTI-PAGE NAVIGATION BAR
page = st.sidebar.radio("Navigate System Pages", ["🏥 Dashboard & Form", "💸 Issue Patient Refund", "🔍 Date-Range Auditor", "⚙️ Procedure Price Settings"])

# ----------------------------------------------------
# PAGE 1: MAIN DASHBOARD & ENTRY FORM
# ----------------------------------------------------
if page == "🏥 Dashboard & Form":
    st.title("🏥 Gastro Dr. Naveed Anwar Clinic Management System")
    st.markdown("---")
    
    col_form, col_display = st.columns(2)
    
    with col_form:
        st.header("📋 Patient Entry Form")
        
        # We handle layout elements inside a dynamic container block to reflect value alterations instantly
        st.info(f"**Date/Time:** {display_datetime_form} \n\n **Receipt No:** `{auto_receipt_no}`")
        
        patient_name = st.text_input("Patient Name *", placeholder="Enter patient's full name")
        selected_procedure = st.selectbox("Select Procedure", list(PROCEDURE_FEES.keys()))
        
        calculated_proc_fee = PROCEDURE_FEES[selected_procedure]
        actual_total = APPT_FEE + calculated_proc_fee
        
        st.markdown(f"""
        * **Appointment Fee:** Rs. {APPT_FEE:,.0f}
        * **Procedure Fee:** Rs. {calculated_proc_fee:,.0f}
        * **Actual Total Amount:** **Rs. {actual_total:,.0f}**
        """)
        
        # FIX: The form submit utilizes interactive widgets directly linked to the actual_total auto-calculated value
        with st.form(key="patient_entry_form", clear_on_submit=True):
            paid_amount = st.number_input("Paid Amount (Rs.)", min_value=0.0, step=500.0, value=actual_total)
            
            # Form actions pass processing instructions downstream
            submit_button = st.form_submit_button(label="Save Record & Auto-Reset")
            
            
            if submit_button:
                if not patient_name.strip():
                    st.error("Submission failed! Patient Name is required.")    
                else:
                # Calculate actual total amount: appointment + procedure - refund (currently 0 on new entry)
                    net_total_bill = APPT_FEE + calculated_proc_fee  # Refund is 0 at entry
            
                    # Remaining balance after paid amount
                    calculated_balance = net_total_bill - paid_amount
            
                    patient_data = {
                        "receipt_no": auto_receipt_no,
                        "date": current_date_str,
                        "datetime_str": display_datetime_form,
                        "timestamp": firestore.SERVER_TIMESTAMP,
                        "patient_name": patient_name.strip(),
                        "procedure": selected_procedure,
                        "appt_fee": APPT_FEE,
                        "procedure_fee": calculated_proc_fee,
                        "actual_amount": net_total_bill,  # Net bill without refund
                        "paid_amount": paid_amount,
                        "refund": 0.0,  # Starts at 0 until updated on refund page
                        "balance": calculated_balance
                    }

                log_ref.document(auto_receipt_no).set(patient_data)
                st.success(f"Saved successfully! Receipt: {auto_receipt_no}")
                st.rerun()
                    
    with col_display:
        st.header("📊 Live Worksheet (New entries add to the BOTTOM)")
        
        docs = log_ref.order_by("timestamp", direction=firestore.Query.ASCENDING).stream()
        data_list = [doc.to_dict() for doc in docs]
        
        if data_list:
            df_master = pd.DataFrame(data_list)
            
            if 'datetime_str' not in df_master.columns:
                df_master['datetime_str'] = df_master['date']
            else:
                df_master['datetime_str'] = df_master['datetime_str'].fillna(df_master['date'])

            df_master['date_parsed'] = pd.to_datetime(df_master['date'])
            today_start = pd.Timestamp(datetime.now().date())
            df_today = df_master[df_master['date_parsed'] >= today_start]
                    
            tab_today, tab_receipt = st.tabs(["📅 Today's Live Records", "🧾 Patient Receipt Generator Viewer"])
            
            with tab_today:
                if not df_today.empty:
                    # Calculate totals based on new accounting rules
                    todays_billings = df_today['actual_amount'].sum()
                    todays_refunds_relief = df_today['refund'].sum()
            
                    # Net billings after doctor relief/refunds
                    net_clinic_billings = todays_billings - todays_refunds_relief
                    total_cash_collected = df_today['paid_amount'].sum()
                    total_pending_balances = df_today['balance'].sum()
            
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Today's Total Billings (Minus Relief)", f"Rs. {net_clinic_billings:,.0f}")
                    m2.metric("Today's Total Collected", f"Rs. {total_cash_collected:,.0f}")
                    m3.metric("Today's Pending Balances", f"Rs. {total_pending_balances:,.0f}")
            
                    columns_to_show = [
                        'receipt_no', 'datetime_str', 'patient_name', 'procedure',
                        'actual_amount', 'paid_amount', 'refund', 'balance'
                    ]
                    st.dataframe(df_today[columns_to_show], use_container_width=True, hide_index=True)
                else:
                    st.warning("No patients entered today yet.")
            
            with tab_receipt:
                st.subheader("Select a Patient Receipt:")
                
                clean_dropdown_options = [
                    f"{row['receipt_no']} | {row['patient_name']}"
                    for _, row in df_master.iterrows()
                ]
                
                selected_option = st.selectbox("Choose Patient Folder", options=clean_dropdown_options)
                
                if selected_option:
                    selected_receipt_no = str(selected_option.split(" | ")[0]).strip()
                    matching_rows = df_master[df_master['receipt_no'] == selected_receipt_no]
                    
                    if not matching_rows.empty:
                        p_info = matching_rows.iloc[0].to_dict()
                        
                        receipt_html = f"""
                        <div id="print-area" style="padding:20px; border:2px solid #008080; border-radius:10px; background-color:#f9f9f9; font-family:monospace;">
                            <h2 style="text-align:center; color:#008080; margin-bottom:0;">DR. NAVEED ANWAR</h2>
                            <p style="text-align:center; margin-top:0; font-size:12px;">Gastroenterology & Hepatology Specialist Clinic</p>
                            <hr style="border-top:1px dashed #008080;">
                            <p><b>Receipt No:</b> {p_info.get('receipt_no','')} <span style="float:right;"><b>Issued:</b> {p_info.get('datetime_str', p_info.get('date',''))}</span></p>
                            <p><b>Patient Name:</b> {p_info.get('patient_name','')}</p>
                            <p><b>Procedure Performed:</b> {p_info.get('procedure','')}</p>
                            <hr style="border-top:1px dashed #ced4da;">
                            <p>Appointment Charges: <span style="float:right;">Rs. {float(p_info.get('appt_fee',0)):,.0f}</span></p>
                            <p>Procedure Charges: <span style="float:right;">Rs. {float(p_info.get('procedure_fee',0)):,.0f}</span></p>
                            <h4 style="margin-bottom:5px;">Actual Total Amount: <span style="float:right;">Rs. {float(p_info.get('actual_amount',0)):,.0f}</span></h4>
                            <p style="color:green; margin-top:0; margin-bottom:5px;">Paid Amount: <span style="float:right;">Rs. {float(p_info.get('paid_amount',0)):,.0f}</span></p>
                            <p style="color:red; margin-top:0; margin-bottom:5px;"><b>Refund Disbursed:</b> <span style="float:right;">Rs. {float(p_info.get('refund',0)):,.0f}</span></p>
                            <hr style="border-top: 2px solid #008080;">
                            <h3 style="color:#008080; margin-top:0;">Net Outstanding Balance: <span style="float:right;">Rs. {float(p_info.get('balance',0)):,.0f}</span></h3>
                        </div>
                        <br/>
                        <button onclick="window.print()" style="background-color:#008080; color:white; padding:10px 20px; border:none; border-radius:5px; cursor:pointer; font-weight:bold; width:100%;">🖨️ Click Here to Print Receipt</button>
                        """
                        components.html(receipt_html, height=450, scrolling=True)
                        
                        st.markdown("---")
                        st.subheader("🗑️ Delete This Record")
                        
                        delete_password = st.text_input("Enter Admin Password to Delete This Record", type="password", key=f"del_pwd_{selected_receipt_no}")
                        
                        if delete_password == "5781":
                            st.warning(f"Are you sure you want to permanently delete receipt {selected_receipt_no}?")
                            confirm_delete = st.checkbox("Yes, I confirm deletion", key=f"del_chk_{selected_receipt_no}")
                            
                            if st.button("🔥 Confirm Hard Delete", key=f"del_btn_{selected_receipt_no}"):
                                if confirm_delete:
                                    log_ref.document(selected_receipt_no).delete()
                                    st.success(f"Record {selected_receipt_no} has been successfully deleted.")
                                    st.rerun()
                                else:
                                    st.info("Please check the confirmation checkbox first.")
                        elif delete_password != "":
                            st.error("Incorrect password. Access denied.")
        else:
            st.info("No records logged in the Cloud Database yet.")
            
# ----------------------------------------------------
# PAGE 2: PAYMENT & REFUND ADJUSTMENT PANEL (FIXED)
# ----------------------------------------------------
elif page == "💸 Issue Patient Refund":
    st.title("💸 Patient Payment & Refund Adjustment Panel")
    st.markdown("---")
    
    docs = log_ref.stream()
    data_list = [doc.to_dict() for doc in docs]
    
    if data_list:
        df_refund = pd.DataFrame(data_list)
        
        receipt_list = df_refund['receipt_no'].tolist()
        name_list = df_refund['patient_name'].tolist()
        clean_dropdown_options = [f"{receipt_list[i]} | {name_list[i]}" for i in range(len(receipt_list))]
        
        st.subheader("Select Patient to Adjust Payment or Refund Details:")
        target_selection = st.selectbox("Search Receipt/Patient Name", options=clean_dropdown_options)
        
       if target_selection:
    
    # SAFELY extract receipt number
    target_receipt = target_selection.split(" | ")[0] if " | " in target_selection else target_selection
    
    # Fetch matching record from today's dataframe
    matching_rows = df_refund[df_refund['receipt_no'] == target_receipt]
    
    if not matching_rows.empty:
        
        # Convert first matching row to dict safely
        p_data = matching_rows.iloc[0].to_dict()
        
        # Safe conversion to float
        def safe_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
        
        current_bal = safe_float(p_data.get('balance', 0))
        
        # Display balance info
        if current_bal > 0:
            st.warning(f"⚠️ This patient has an outstanding balance of **Rs. {current_bal:,.0f}**")
        else:
            st.success("✅ This patient's account is fully cleared.")
        
        # Show current patient record
        st.write("**Current Registered Record Details:**")
        st.json({
            "Patient Name": p_data.get('patient_name', ''),
            "Procedure": p_data.get('procedure', ''),
            "Actual Total Cost": f"Rs. {safe_float(p_data.get('actual_amount')):,.0f}",
            "Paid So Far": f"Rs. {safe_float(p_data.get('paid_amount')):,.0f}",
            "Existing Registered Refund": f"Rs. {safe_float(p_data.get('refund')):,.0f}"
        })
        
        # Adjustment form
        with st.form("refund_update_form"):
            
            updated_paid = st.number_input(
                "Update Total Paid Amount (Rs.)",
                min_value=0.0,
                value=safe_float(p_data.get('paid_amount')),
                step=500.0,
                help="Increase this amount when patient pays remaining balance."
            )
            
            new_refund = st.number_input(
                "Update Total Refund Amount (Rs.)",
                min_value=0.0,
                value=safe_float(p_data.get('refund')),
                step=500.0
            )
            
            submit_adjustments = st.form_submit_button("Save Changes to Cloud")
            
            if submit_adjustments:
                base_amount = safe_float(p_data.get('actual_amount'))
                
                # Calculate new balance after refund and payment
                updated_balance = max(0.0, (base_amount - new_refund) - updated_paid)
                
                # Update Firestore
                log_ref.document(target_receipt).update({
                    "paid_amount": updated_paid,
                    "refund": new_refund,
                    "balance": updated_balance
                })
                
                st.success(f"Updated successfully! New Balance: Rs. {updated_balance:,.0f}")
                
                # Refresh page to reflect changes
                st.rerun()
                
    else:
        st.warning("No matching patient record found for selected receipt.")
        
else:
    st.info("No logs present to process adjustments.")
# ----------------------------------------------------
# PAGE 3: DATE-RANGE AUDITOR ARCHIVE (FIXED)
# ----------------------------------------------------
elif page == "🔍 Date-Range Auditor":
    st.title("🔍 Advanced Historical Audit & Custom Date Filters")
    st.markdown("---")
    
    docs = log_ref.stream()
    data_list = [doc.to_dict() for doc in docs]
    
    if data_list:
        df_audit = pd.DataFrame(data_list)
        df_audit['date_parsed'] = pd.to_datetime(
            df_audit['date'],
            errors='coerce'
        ).dt.date
        
        c1, c2 = st.columns(2)
        start_date = c1.date_input("From Date", datetime.now().date() - timedelta(days=7))
        end_date = c2.date_input("To Date", datetime.now().date())
        
        if start_date <= end_date:
            filtered_df = df_audit[
                (df_audit['date_parsed'].notna()) &
                (df_audit['date_parsed'] >= start_date) &
                (df_audit['date_parsed'] <= end_date)
            ]
            
            if not filtered_df.empty:
                st.subheader("📊 Aggregated Summaries")
                
                a1, a2, a3, a4 = st.columns(4)
                
                a1.metric(
                    "Total Appointment Fees",
                    f"Rs. {filtered_df.get('appt_fee', pd.Series()).sum():,.0f}"
                )
                
                a2.metric(
                    "Total Surgery/Proc Billings",
                    f"Rs. {filtered_df.get('procedure_fee', pd.Series()).sum():,.0f}"
                )
                
                a3.metric(
                    "Grand Cash Collected",
                    f"Rs. {filtered_df.get('paid_amount', pd.Series()).sum():,.0f}"
                )
                
                a4.metric(
                    "Total Patients Processed",
                    f"{len(filtered_df)} Patients"
                )
                
                st.markdown("---")
                st.subheader("📋 Count & Revenue Breakdown per Surgery/Procedure Type")
                
                if 'procedure' in filtered_df.columns:
                    proc_breakdown = filtered_df.groupby('procedure').agg(
                        Total_Count=('patient_name', 'count'),
                        Total_Revenue=('procedure_fee', 'sum')
                    ).reset_index()
                    
                    st.dataframe(proc_breakdown, use_container_width=True, hide_index=True)
                else:
                    st.warning("Procedure data not available for grouping.")
                
                st.markdown("---")
                st.subheader("🗄️ Detailed Matching Patient Sub-List")
                
                drop_cols = [c for c in ['timestamp', 'date_parsed'] if c in filtered_df.columns]
                st.dataframe(filtered_df.drop(columns=drop_cols), use_container_width=True, hide_index=True)
            else:
                st.warning("No clinic documents match the selected date constraints.")
        else:
            st.error("Start date must be before or equal to end date.")
    else:
        st.info("No data available in database.")

# ----------------------------------------------------
# PAGE 4: PRICING SETTINGS MANAGER (FIXED)
# ----------------------------------------------------
elif page == "⚙️ Procedure Price Settings":
    st.title("⚙️ Clinic Control Panel & Pricing Administration")
    st.markdown("---")
    
    with st.form("settings_form"):
        new_appt = st.number_input(
            "Universal Consultation/Appointment Fee (Rs.)",
            min_value=0.0,
            value=float(APPT_FEE),
            step=500.0
        )
        
        updated_fees = {"appt_fee": new_appt}
        
        for proc, current_fee in PROCEDURE_FEES.items():
            safe_fee = float(current_fee) if current_fee is not None else 0.0
            
            if proc != "None (Consultation Only)":
                updated_fees[proc] = st.number_input(
                    f"{proc} Fee Cost (Rs.)",
                    min_value=0.0,
                    value=safe_fee,
                    step=500.0
                )
            else:
                updated_fees[proc] = 0.0
        
        save_settings = st.form_submit_button("Update Rates Globally")
        
        if save_settings:
            settings_ref.document("pricing").set(updated_fees, merge=True)
            st.success("Clinic pricing configurations synchronized successfully!")
            st.rerun()
