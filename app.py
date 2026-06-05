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
# 🧭 MULTI-PAGE NAVIGATION BAR
# ----------------------------------------------------
page = st.sidebar.radio(
    "Navigate System Pages",
    ["🏥 Dashboard & Form", "💸 Issue Patient Refund", "🔍 Date-Range Auditor", "⚙️ Procedure Price Settings"]
)

# ----------------------------------------------------
# PAGE 1: MAIN DASHBOARD & ENTRY FORM
# ----------------------------------------------------
if page == "🏥 Dashboard & Form":
    st.title("🏥 Gastro Dr. Naveed Anwar Clinic Management System")
    st.markdown("---")

    col_form, col_display = st.columns(2)

    with col_form:
        st.header("📋 Patient Entry Form")

        with st.form(key="patient_entry_form", clear_on_submit=True):
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

            paid_amount = st.number_input(
                "Paid Amount (Rs.)",
                min_value=0.0,
                step=500.0,
                value=float(actual_total)
            )

            refund_amount = st.number_input(
                "Refund Amount (Rs.)",
                min_value=0.0,
                step=500.0,
                value=0.0
            )

            calculated_balance = actual_total - paid_amount + refund_amount
            st.markdown(f"**Calculated Balance:** Rs. {calculated_balance:,.0f}")

            submit_button = st.form_submit_button(label="Save Record & Auto-Reset")

            if submit_button:
                if not patient_name.strip():
                    st.error("Submission failed! Patient Name is required.")
                else:
                    patient_data = {
                        "receipt_no": auto_receipt_no,
                        "date": current_date_str,
                        "datetime_str": display_datetime_form,
                        "timestamp": firestore.SERVER_TIMESTAMP,
                        "patient_name": patient_name.strip(),
                        "procedure": selected_procedure,
                        "appt_fee": APPT_FEE,
                        "procedure_fee": calculated_proc_fee,
                        "actual_amount": actual_total,
                        "paid_amount": paid_amount,
                        "refund": refund_amount,
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
            df_master["date_parsed"] = pd.to_datetime(df_master["date"])
            today_start = pd.Timestamp(datetime.now().date())
            df_today = df_master[df_master["date_parsed"] >= today_start]

            tab_today, tab_receipt = st.tabs(
                ["📅 Today's Live Records", "🧾 Patient Receipt Generator Viewer"]
            )

            with tab_today:
                if not df_today.empty:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Today's Total Billings", f"Rs. {df_today['actual_amount'].sum():,.0f}")
                    m2.metric("Today's Total Collected", f"Rs. {df_today['paid_amount'].sum():,.0f}")
                    m3.metric("Today's Pending Balances", f"Rs. {df_today['balance'].sum():,.0f}")

                    columns_to_show = [
                        "receipt_no",
                        "datetime_str",
                        "patient_name",
                        "procedure",
                        "actual_amount",
                        "paid_amount",
                        "refund",
                        "balance",
                    ]

                    st.dataframe(df_today[columns_to_show], use_container_width=True, hide_index=True)
                else:
                    st.warning("No patients entered today yet.")

            with tab_receipt:
                st.subheader("Select a Patient Receipt:")

                receipt_list = df_master["receipt_no"].tolist()
                name_list = df_master["patient_name"].tolist()
                clean_dropdown_options = [
                    f"{receipt_list[i]} | {name_list[i]}" for i in range(len(receipt_list))
                ]

                selected_option = st.selectbox("Choose Patient Folder", options=clean_dropdown_options)

                if selected_option:
                    selected_receipt_no = selected_option.split(" | ")[0]
                    matching_rows = df_master[df_master["receipt_no"] == selected_receipt_no]

                    if not matching_rows.empty:
                        p_info = matching_rows.iloc[0].to_dict()

                        receipt_html = f"""
                        <div id="print-area" style="padding:20px;border:2px solid #008080;border-radius:10px;background:#f9f9f9;font-family:monospace;">
                            <h2 style="text-align:center;color:#008080;">DR. NAVEED ANWAR</h2>
                            <p style="text-align:center;font-size:12px;">Gastroenterology & Hepatology Specialist Clinic</p>
                            <hr>
                            <p><b>Receipt No:</b> {p_info['receipt_no']} <span style="float:right;"><b>Issued:</b> {p_info.get('datetime_str', p_info['date'])}</span></p>
                            <p><b>Patient Name:</b> {p_info['patient_name']}</p>
                            <p><b>Procedure:</b> {p_info['procedure']}</p>
                            <hr>
                            <p>Appointment: <span style="float:right;">Rs. {float(p_info['appt_fee']):,.0f}</span></p>
                            <p>Procedure: <span style="float:right;">Rs. {float(p_info['procedure_fee']):,.0f}</span></p>
                            <h4>Total: <span style="float:right;">Rs. {float(p_info['actual_amount']):,.0f}</span></h4>
                            <p style="color:green;">Paid: <span style="float:right;">Rs. {float(p_info['paid_amount']):,.0f}</span></p>
                            <p style="color:red;">Refund: <span style="float:right;">Rs. {float(p_info['refund']):,.0f}</span></p>
                            <hr>
                            <h3 style="color:#008080;">Balance: <span style="float:right;">Rs. {float(p_info['balance']):,.0f}</span></h3>
                        </div>
                        <button onclick="window.print()" style="width:100%;padding:10px;background:#008080;color:white;">Print</button>
                        """

                        components.html(receipt_html, height=450)

        else:
            st.info("No records logged in the Cloud Database yet.")

# ----------------------------------------------------
# PAGE 2: REFUND PROCESSING PANEL
# ----------------------------------------------------
elif page == "💸 Issue Patient Refund":
    st.title("💸 Doctor Approved Refund Manager Panel")
    st.markdown("---")

    docs = log_ref.stream()
    data_list = [doc.to_dict() for doc in docs]

    if data_list:
        df_refund = pd.DataFrame(data_list)

        receipt_list = df_refund["receipt_no"].tolist()
        name_list = df_refund["patient_name"].tolist()

        clean_dropdown_options = [
            f"{receipt_list[i]} | {name_list[i]}"
            for i in range(len(receipt_list))
        ]

        st.subheader("Select Patient to Alter/Issue Refund Details:")
        target_selection = st.selectbox("Search Receipt/Patient Name", options=clean_dropdown_options)

        if target_selection:
            target_receipt = target_selection.split(" | ")[0]

            p_data = df_refund[df_refund["receipt_no"] == target_receipt].iloc[0].to_dict()

            st.write("**Current Registered Record Details:**")

            st.json({
                "Patient Name": p_data["patient_name"],
                "Procedure": p_data["procedure"],
                "Actual Total Cost": f"Rs. {p_data['actual_amount']:,.0f}",
                "Paid So Far": f"Rs. {p_data['paid_amount']:,.0f}",
                "Existing Registered Refund": f"Rs. {p_data['refund']:,.0f}"
            })

            with st.form("refund_update_form"):
                new_refund = st.number_input(
                    "Enter New Updated Total Refund Amount (Rs.)",
                    min_value=0.0,
                    value=float(p_data["refund"]),
                    step=500.0
                )

                submit_refund = st.form_submit_button("Save Refund Changes to Cloud")

                if submit_refund:
                    updated_balance = (
                        float(p_data["actual_amount"])
                        - float(p_data["paid_amount"])
                        + new_refund
                    )

                    log_ref.document(target_receipt).update({
                        "refund": new_refund,
                        "balance": updated_balance
                    })

                    st.success(
                        f"Balances updated successfully for {p_data['patient_name']}! "
                        f"New Balance: Rs. {updated_balance:,.0f}"
                    )

                    st.rerun()

    else:
        st.info("No logs present to process refunds.")


# ----------------------------------------------------
# PAGE 3: DATE-RANGE AUDITOR ARCHIVE
# ----------------------------------------------------
elif page == "🔍 Date-Range Auditor":
    st.title("🔍 Advanced Historical Audit & Custom Date Filters")
    st.markdown("---")

    docs = log_ref.stream()
    data_list = [doc.to_dict() for doc in docs]

    if data_list:
        df_audit = pd.DataFrame(data_list)

        df_audit["date_parsed"] = pd.to_datetime(df_audit["date"]).dt.date

        c1, c2 = st.columns(2)

        start_date = c1.date_input(
            "From Date",
            datetime.now().date() - timedelta(days=7)
        )

        end_date = c2.date_input(
            "To Date",
            datetime.now().date()
        )

        if start_date <= end_date:

            filtered_df = df_audit[
                (df_audit["date_parsed"] >= start_date) &
                (df_audit["date_parsed"] <= end_date)
            ]

            if not filtered_df.empty:
                st.subheader("📊 Aggregated Summaries")

                a1, a2, a3, a4 = st.columns(4)

                a1.metric("Total Appointment Fees", f"Rs. {filtered_df['appt_fee'].sum():,.0f}")
                a2.metric("Total Procedure Billings", f"Rs. {filtered_df['procedure_fee'].sum():,.0f}")
                a3.metric("Grand Cash Collected", f"Rs. {filtered_df['paid_amount'].sum():,.0f}")
                a4.metric("Total Patients", f"{len(filtered_df)} Patients")

                st.markdown("---")
                st.subheader("📋 Count & Revenue per Procedure")

                proc_breakdown = filtered_df.groupby("procedure").agg(
                    Total_Count=("patient_name", "count"),
                    Total_Revenue=("procedure_fee", "sum")
                ).reset_index()

                st.dataframe(proc_breakdown, use_container_width=True, hide_index=True)

                st.markdown("---")
                st.subheader("🗄️ Detailed Patient Records")

                st.dataframe(
                    filtered_df.drop(columns=["timestamp", "date_parsed"]),
                    use_container_width=True,
                    hide_index=True
                )

            else:
                st.warning("No clinic documents match the selected date range.")


# ----------------------------------------------------
# PAGE 4: PRICING SETTINGS MANAGER
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
            if proc != "None (Consultation Only)":
                updated_fees[proc] = st.number_input(
                    f"{proc} Fee Cost (Rs.)",
                    min_value=0.0,
                    value=float(current_fee),
                    step=500.0
                )
            else:
                updated_fees[proc] = 0.0

        save_settings = st.form_submit_button("Update Rates Globally")

        if save_settings:
            settings_ref.document("pricing").set(updated_fees)
            st.success("Clinic pricing configurations synchronized successfully!")
            st.rerun()
