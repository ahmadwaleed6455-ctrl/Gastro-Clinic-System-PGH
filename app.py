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
            
            paid_amount = st.number_input("Paid Amount (Rs.)", min_value=0.0, step=500.0, value=actual_total)
            refund_amount = st.number_input("Refund Amount (Rs.)", min_value=0.0, step=500.0, value=0.0)
            
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

    try:
        docs = log_ref.order_by(
            "timestamp",
            direction=firestore.Query.ASCENDING
        ).stream()
    except Exception:
        docs = log_ref.stream()

    data_list = [doc.to_dict() for doc in docs]

    if data_list:

        df_master = pd.DataFrame(data_list)

        # ------------------------------------------------
        # Ensure required columns always exist
        # ------------------------------------------------
        required_columns = {
            "receipt_no": "",
            "date": current_date_str,
            "datetime_str": "",
            "patient_name": "",
            "procedure": "",
            "appt_fee": 0,
            "procedure_fee": 0,
            "actual_amount": 0,
            "paid_amount": 0,
            "refund": 0,
            "balance": 0,
        }

        for col, default in required_columns.items():
            if col not in df_master.columns:
                df_master[col] = default

        # ------------------------------------------------
        # Convert numeric fields safely
        # ------------------------------------------------
        numeric_cols = [
            "appt_fee",
            "procedure_fee",
            "actual_amount",
            "paid_amount",
            "refund",
            "balance",
        ]

        for col in numeric_cols:
            df_master[col] = pd.to_numeric(
                df_master[col],
                errors="coerce"
            ).fillna(0)

        # ------------------------------------------------
        # Safe date conversion
        # ------------------------------------------------
        df_master["date_parsed"] = pd.to_datetime(
            df_master["date"],
            errors="coerce"
        )

        today_start = pd.Timestamp(datetime.now().date())

        df_today = df_master[
            df_master["date_parsed"] >= today_start
        ]

        tab_today, tab_receipt = st.tabs(
            [
                "📅 Today's Live Records",
                "🧾 Patient Receipt Generator Viewer"
            ]
        )

        # =================================================
        # TODAY TAB
        # =================================================
        with tab_today:

            if not df_today.empty:

                m1, m2, m3 = st.columns(3)

                m1.metric(
                    "Today's Total Billings",
                    f"Rs. {df_today['actual_amount'].sum():,.0f}"
                )

                m2.metric(
                    "Today's Total Collected",
                    f"Rs. {df_today['paid_amount'].sum():,.0f}"
                )

                m3.metric(
                    "Today's Pending Balances",
                    f"Rs. {df_today['balance'].sum():,.0f}"
                )

                columns_to_show = [
                    "receipt_no",
                    "datetime_str",
                    "patient_name",
                    "procedure",
                    "actual_amount",
                    "paid_amount",
                    "refund",
                    "balance"
                ]

                st.dataframe(
                    df_today.reindex(columns=columns_to_show),
                    use_container_width=True,
                    hide_index=True
                )

            else:
                st.warning("No patients entered today yet.")

        # =================================================
        # RECEIPT TAB
        # =================================================
        with tab_receipt:

            st.subheader("Select a Patient Receipt")

            receipt_options = [
                f"{row['receipt_no']} | {row['patient_name']}"
                for _, row in df_master.iterrows()
            ]

            if receipt_options:

                selected_option = st.selectbox(
                    "Choose Patient Folder",
                    receipt_options
                )

                if selected_option:

                    # FIXED
                    selected_receipt_no = selected_option.split(" | ")[0]

                    matching_rows = df_master[
                        df_master["receipt_no"] == selected_receipt_no
                    ]

                    if not matching_rows.empty:

                        p_info = matching_rows.iloc[0].to_dict()

                        receipt_html = f"""
                        <div id="print-area"
                             style="padding:20px;
                                    border:2px solid #008080;
                                    border-radius:10px;
                                    background-color:#f9f9f9;
                                    font-family:monospace;">

                            <h2 style="text-align:center;
                                       color:#008080;
                                       margin-bottom:0;">
                                DR. NAVEED ANWAR
                            </h2>

                            <p style="text-align:center;
                                      margin-top:0;
                                      font-size:12px;">
                                Gastroenterology & Hepatology Specialist Clinic
                            </p>

                            <hr style="border-top:1px dashed #008080;">

                            <p>
                                <b>Receipt No:</b>
                                {p_info.get('receipt_no','')}
                                <span style="float:right;">
                                    <b>Issued:</b>
                                    {p_info.get('datetime_str','')}
                                </span>
                            </p>

                            <p>
                                <b>Patient Name:</b>
                                {p_info.get('patient_name','')}
                            </p>

                            <p>
                                <b>Procedure Performed:</b>
                                {p_info.get('procedure','')}
                            </p>

                            <hr style="border-top:1px dashed #ced4da;">

                            <p>
                                Appointment Charges:
                                <span style="float:right;">
                                    Rs. {float(p_info.get('appt_fee',0)):,.0f}
                                </span>
                            </p>

                            <p>
                                Procedure Charges:
                                <span style="float:right;">
                                    Rs. {float(p_info.get('procedure_fee',0)):,.0f}
                                </span>
                            </p>

                            <h4 style="margin-bottom:5px;">
                                Actual Total Amount:
                                <span style="float:right;">
                                    Rs. {float(p_info.get('actual_amount',0)):,.0f}
                                </span>
                            </h4>

                            <p style="color:green;">
                                Paid Amount:
                                <span style="float:right;">
                                    Rs. {float(p_info.get('paid_amount',0)):,.0f}
                                </span>
                            </p>

                            <p style="color:red;">
                                <b>Refund Disbursed:</b>
                                <span style="float:right;">
                                    Rs. {float(p_info.get('refund',0)):,.0f}
                                </span>
                            </p>

                            <hr style="border-top:2px solid #008080;">

                            <h3 style="color:#008080;">
                                Net Outstanding Balance:
                                <span style="float:right;">
                                    Rs. {float(p_info.get('balance',0)):,.0f}
                                </span>
                            </h3>
                        </div>

                        <br>

                        <button onclick="window.print()"
                                style="background:#008080;
                                       color:white;
                                       padding:10px 20px;
                                       border:none;
                                       border-radius:5px;
                                       width:100%;
                                       cursor:pointer;">
                            🖨️ Click Here to Print Receipt
                        </button>
                        """

                        components.html(
                            receipt_html,
                            height=500,
                            scrolling=True
                        )

    else:
        st.info("No records logged in the Cloud Database yet.")

# ----------------------------------------------------

# PAGE 2: REFUND PROCESSING PANEL

# ----------------------------------------------------

elif page == "💸 Issue Patient Refund":

```
st.title("💸 Doctor Approved Refund Manager Panel")
st.markdown("---")

docs = log_ref.stream()
data_list = [doc.to_dict() for doc in docs]

if data_list:

    df_refund = pd.DataFrame(data_list)

    required_cols = {
        "receipt_no": "",
        "patient_name": "",
        "procedure": "",
        "actual_amount": 0,
        "paid_amount": 0,
        "refund": 0,
        "balance": 0,
    }

    for col, default in required_cols.items():
        if col not in df_refund.columns:
            df_refund[col] = default

    for col in [
        "actual_amount",
        "paid_amount",
        "refund",
        "balance"
    ]:
        df_refund[col] = pd.to_numeric(
            df_refund[col],
            errors="coerce"
        ).fillna(0)

    clean_dropdown_options = [
        f"{row['receipt_no']} | {row['patient_name']}"
        for _, row in df_refund.iterrows()
    ]

    st.subheader(
        "Select Patient to Alter / Issue Refund Details"
    )

    target_selection = st.selectbox(
        "Choose Patient",
        clean_dropdown_options
    )

    if target_selection:

        target_receipt = target_selection.split(" | ")[0]

        matching_rows = df_refund[
            df_refund["receipt_no"] == target_receipt
        ]

        if not matching_rows.empty:

            p_data = matching_rows.iloc[0].to_dict()

            st.write("### Current Registered Record")

            st.json({
                "Patient Name":
                    p_data.get("patient_name", ""),
                "Procedure":
                    p_data.get("procedure", ""),
                "Actual Total Cost":
                    f"Rs. {float(p_data.get('actual_amount',0)):,.0f}",
                "Paid So Far":
                    f"Rs. {float(p_data.get('paid_amount',0)):,.0f}",
                "Current Refund":
                    f"Rs. {float(p_data.get('refund',0)):,.0f}",
                "Current Balance":
                    f"Rs. {float(p_data.get('balance',0)):,.0f}",
            })

            with st.form("refund_update_form"):

                new_refund = st.number_input(
                    "Updated Refund Amount (Rs.)",
                    min_value=0.0,
                    value=float(
                        p_data.get("refund", 0)
                    ),
                    step=500.0
                )

                submit_refund = st.form_submit_button(
                    "Save Refund Changes"
                )

                if submit_refund:

                    updated_balance = (
                        float(
                            p_data.get(
                                "actual_amount",
                                0
                            )
                        )
                        - float(
                            p_data.get(
                                "paid_amount",
                                0
                            )
                        )
                        + new_refund
                    )

                    log_ref.document(
                        str(target_receipt)
                    ).update({
                        "refund": new_refund,
                        "balance": updated_balance
                    })

                    st.success(
                        f"Refund updated successfully. "
                        f"New Balance: Rs. {updated_balance:,.0f}"
                    )

                    st.rerun()

else:
    st.info(
        "No logs present to process refunds."
    )
```

# ----------------------------------------------------

# PAGE 3: DATE-RANGE AUDITOR ARCHIVE

# ----------------------------------------------------

elif page == "🔍 Date-Range Auditor":

```
st.title(
    "🔍 Advanced Historical Audit & Custom Date Filters"
)

st.markdown("---")

docs = log_ref.stream()
data_list = [doc.to_dict() for doc in docs]

if data_list:

    df_audit = pd.DataFrame(data_list)

    required_cols = {
        "date": current_date_str,
        "patient_name": "",
        "procedure": "",
        "appt_fee": 0,
        "procedure_fee": 0,
        "actual_amount": 0,
        "paid_amount": 0,
        "refund": 0,
        "balance": 0,
    }

    for col, default in required_cols.items():
        if col not in df_audit.columns:
            df_audit[col] = default

    numeric_cols = [
        "appt_fee",
        "procedure_fee",
        "actual_amount",
        "paid_amount",
        "refund",
        "balance"
    ]

    for col in numeric_cols:
        df_audit[col] = pd.to_numeric(
            df_audit[col],
            errors="coerce"
        ).fillna(0)

    df_audit["date_parsed"] = pd.to_datetime(
        df_audit["date"],
        errors="coerce"
    ).dt.date

    c1, c2 = st.columns(2)

    start_date = c1.date_input(
        "From Date",
        datetime.now().date()
        - timedelta(days=7)
    )

    end_date = c2.date_input(
        "To Date",
        datetime.now().date()
    )

    if start_date <= end_date:

        filtered_df = df_audit[
            (df_audit["date_parsed"] >= start_date)
            &
            (df_audit["date_parsed"] <= end_date)
        ]

        if not filtered_df.empty:

            st.subheader(
                "📊 Aggregated Summaries"
            )

            a1, a2, a3, a4 = st.columns(4)

            a1.metric(
                "Total Appointment Fees",
                f"Rs. {filtered_df['appt_fee'].sum():,.0f}"
            )

            a2.metric(
                "Procedure Revenue",
                f"Rs. {filtered_df['procedure_fee'].sum():,.0f}"
            )

            a3.metric(
                "Cash Collected",
                f"Rs. {filtered_df['paid_amount'].sum():,.0f}"
            )

            a4.metric(
                "Patients Processed",
                len(filtered_df)
            )

            st.markdown("---")

            st.subheader(
                "📋 Procedure Revenue Breakdown"
            )

            proc_breakdown = (
                filtered_df
                .groupby("procedure")
                .agg(
                    Total_Count=(
                        "patient_name",
                        "count"
                    ),
                    Total_Revenue=(
                        "procedure_fee",
                        "sum"
                    )
                )
                .reset_index()
            )

            st.dataframe(
                proc_breakdown,
                use_container_width=True,
                hide_index=True
            )

            st.markdown("---")

            st.subheader(
                "🗄️ Detailed Patient Listing"
            )

            cols_to_drop = [
                c for c in
                ["timestamp", "date_parsed"]
                if c in filtered_df.columns
            ]

            st.dataframe(
                filtered_df.drop(
                    columns=cols_to_drop
                ),
                use_container_width=True,
                hide_index=True
            )

        else:
            st.warning(
                "No clinic records found "
                "within selected dates."
            )

else:
    st.info(
        "No audit data available."
    )
```

# ----------------------------------------------------

# PAGE 4: PRICING SETTINGS MANAGER

# ----------------------------------------------------

elif page == "⚙️ Procedure Price Settings":

```
st.title(
    "⚙️ Clinic Control Panel & Pricing Administration"
)

st.markdown("---")

with st.form("settings_form"):

    new_appt = st.number_input(
        "Universal Consultation Fee (Rs.)",
        min_value=0.0,
        value=float(APPT_FEE),
        step=500.0
    )

    updated_fees = {
        "appt_fee": new_appt
    }

    for proc, current_fee in PROCEDURE_FEES.items():

        if proc == "None (Consultation Only)":
            updated_fees[proc] = 0.0
            continue

        updated_fees[proc] = st.number_input(
            f"{proc} Fee (Rs.)",
            min_value=0.0,
            value=float(current_fee),
            step=500.0
        )

    save_settings = st.form_submit_button(
        "Update Rates Globally"
    )

    if save_settings:

        settings_ref.document(
            "pricing"
        ).set(updated_fees)

        st.success(
            "Pricing updated successfully."
        )

        st.rerun()

