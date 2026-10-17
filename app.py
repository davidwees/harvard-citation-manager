import re
import hashlib
import streamlit as st
import pandas as pd
from supabase import create_client, Client

# Initialize Supabase Client
@st.cache_resource
def init_supabase() -> Client:
    # Fetch credentials from Streamlit Secrets or environment
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# Helper Functions: Auth
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    try:
        response = supabase.table("users").insert({
            "username": username,
            "password_hash": hash_password(password)
        }).execute()
        return True if response.data else False
    except Exception:
        return False

def authenticate_user(username, password):
    response = supabase.table("users") \
        .select("*") \
        .eq("username", username) \
        .eq("password_hash", hash_password(password)) \
        .execute()
    return response.data[0] if response.data else None

# Helper Functions: Citation Parsing & Sorting
def parse_harvard_citation(text):
    clean_text = text.strip()
    
    url_match = re.search(r'Available at:\s*(https?://[^\s]+)', clean_text, re.IGNORECASE)
    url = url_match.group(1).rstrip('.') if url_match else ""
    
    main_text = re.sub(r'Available at:\s*https?://[^\s]+', '', clean_text, flags=re.IGNORECASE).strip()

    author_year_match = re.match(r'^(.*?)\s*\((.*?)\)(.*)$', main_text)
    
    if author_year_match:
        authors = author_year_match.group(1).strip()
        year = author_year_match.group(2).strip()
        rest = author_year_match.group(3).strip()
        
        parts = re.split(r'(?<=[.?!])\s+', rest, maxsplit=1)
        title = parts[0].strip() if len(parts) > 0 else rest
        source = parts[1].strip() if len(parts) > 1 else ""
    else:
        authors = ""
        year = ""
        title = main_text
        source = ""

    return {
        "raw_text": clean_text,
        "authors": authors,
        "year": year,
        "title": title,
        "source": source,
        "url": url
    }

def get_first_author_surname(authors_str):
    if not authors_str or not authors_str.strip():
        return "ZZZ_UNKNOWN"
    
    first_author = re.split(r'\s+and\s+|\s*&\s*|;', authors_str, flags=re.IGNORECASE)[0].strip()
    
    if ',' in first_author:
        surname = first_author.split(',')[0].strip()
    else:
        words = [w for w in first_author.split() if not w.endswith('.')]
        surname = words[-1] if words else first_author
        
    return surname.lower()

# Database Operations (Folders)
def create_folder(user_id, folder_name):
    supabase.table("folders").insert({
        "user_id": user_id,
        "name": folder_name.strip()
    }).execute()

def get_user_folders(user_id):
    response = supabase.table("folders") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("name") \
        .execute()
    return response.data or []

def delete_folder(folder_id):
    supabase.table("folders").delete().eq("id", folder_id).execute()

# Database Operations (Citations)
def save_citation(user_id, parsed_data, folder_id=None, notes=""):
    payload = {
        "user_id": user_id,
        "folder_id": folder_id,
        "raw_text": parsed_data["raw_text"],
        "authors": parsed_data["authors"],
        "year": parsed_data["year"],
        "title": parsed_data["title"],
        "source": parsed_data["source"],
        "url": parsed_data["url"],
        "notes": notes
    }
    supabase.table("citations").insert(payload).execute()

def get_user_citations(user_id, folder_id=None):
    query = supabase.table("citations").select("*, folders(name)")
    query = query.eq("user_id", user_id)
    
    if folder_id is not None:
        query = query.eq("folder_id", folder_id)
        
    response = query.order("id").execute()
    
    # Flatten joined folder name for consistency
    results = []
    for row in response.data or []:
        row["folder_name"] = row["folders"]["name"] if row.get("folders") else None
        results.append(row)
    return results

def update_citation_folder_and_notes(citation_id, folder_id, notes):
    supabase.table("citations").update({
        "folder_id": folder_id,
        "notes": notes
    }).eq("id", citation_id).execute()

def delete_citation(citation_id):
    supabase.table("citations").delete().eq("id", citation_id).execute()


# App Interface
st.set_page_config(page_title="Harvard Citation Manager", page_icon="📚", layout="wide")

if "user" not in st.session_state:
    st.session_state.user = None

# Sidebar Authentication
st.sidebar.title("👤 User Account")

if st.session_state.user is None:
    auth_mode = st.sidebar.radio("Select Action", ["Login", "Register"])
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")

    if auth_mode == "Register":
        if st.sidebar.button("Register"):
            if username and password:
                if register_user(username, password):
                    st.sidebar.success("Account created! Please log in.")
                else:
                    st.sidebar.error("Username already exists or error occurred.")
            else:
                st.sidebar.warning("Please fill in both fields.")
    else:
        if st.sidebar.button("Login"):
            user = authenticate_user(username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.sidebar.error("Invalid username or password.")
else:
    user_id = st.session_state.user["id"]
    st.sidebar.write(f"Logged in as **{st.session_state.user['username']}**")
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

    st.sidebar.divider()
    st.sidebar.title("📁 Folders")
    
    new_folder_name = st.sidebar.text_input("New Folder Name", key="new_folder_input")
    if st.sidebar.button("Create Folder"):
        if new_folder_name.strip():
            create_folder(user_id, new_folder_name.strip())
            st.sidebar.success(f"Folder '{new_folder_name}' created!")
            st.rerun()

    folders = get_user_folders(user_id)
    folder_options = {"All Citations": None}
    for f in folders:
        folder_options[f"📁 {f['name']}"] = f["id"]

    selected_folder_label = st.sidebar.radio(
        "Filter / Manage View:",
        options=list(folder_options.keys())
    )
    selected_folder_id = folder_options[selected_folder_label]

    if selected_folder_id is not None:
        if st.sidebar.button("Delete Current Folder", type="secondary"):
            delete_folder(selected_folder_id)
            st.sidebar.warning("Folder deleted.")
            st.rerun()

# Main Application
st.title("📚 Harvard Citation Manager")

if st.session_state.user is None:
    st.info("Please log in or register from the sidebar to manage your citations.")
else:
    user_id = st.session_state.user["id"]
    user_folders = get_user_folders(user_id)

    tab_add, tab_view, tab_export = st.tabs(["➕ Add Citation", "📋 Manage Citations & Notes", "📤 Export"])

    # --- TAB 1: ADD CITATION ---
    with tab_add:
        st.subheader("Paste Harvard Citation")
        citation_input = st.text_area(
            "Paste citation text here:",
            height=120,
            placeholder="e.g. Siddiqui & Wardle (2020) Can users judge what is 'promising' evidence in education? Research Intelligence 144 (Autumn 2020). Available at: https://durham-repository.worktribe.com/output/1261808/"
        )
        
        col_f, col_n = st.columns([1, 2])
        with col_f:
            folder_choices = {"Unassigned": None}
            for f in user_folders:
                folder_choices[f["name"]] = f["id"]
            assign_folder = st.selectbox("Assign to Folder:", options=list(folder_choices.keys()))
            chosen_folder_id = folder_choices[assign_folder]
            
        with col_n:
            initial_note = st.text_area("Optional Note:", placeholder="Add research notes or summary...", height=68)

        if st.button("Parse & Save Citation", type="primary"):
            if citation_input.strip():
                parsed = parse_harvard_citation(citation_input)
                save_citation(user_id, parsed, chosen_folder_id, initial_note)
                st.success("Citation saved to Supabase!")
                st.rerun()
            else:
                st.warning("Please paste a citation before saving.")

    # --- TAB 2: MANAGE CITATIONS & NOTES ---
    with tab_view:
        st.subheader(f"Citations ({selected_folder_label})")
        records = get_user_citations(user_id, selected_folder_id)

        if not records:
            st.info("No citations found.")
        else:
            sort_by_author = st.checkbox("Sort display by First Author Surname (A-Z)", value=True)
            if sort_by_author:
                records.sort(key=lambda x: get_first_author_surname(x["authors"]))

            for row in records:
                folder_tag = f" [{row['folder_name']}]" if row.get("folder_name") else " [Unassigned]"
                with st.expander(f"📌 #{row['id']} - {row['authors'] or 'Unknown Author'} ({row['year'] or 'n.d.'}){folder_tag}"):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.markdown(f"**Raw Entry:** {row['raw_text']}")
                        st.markdown(f"**Authors:** {row['authors'] or 'N/A'}")
                        st.markdown(f"**Year:** {row['year'] or 'N/A'}")
                        st.markdown(f"**Title:** {row['title'] or 'N/A'}")
                        st.markdown(f"**Source:** {row['source'] or 'N/A'}")
                        if row["url"]:
                            st.markdown(f"**URL:** [{row['url']}]({row['url']})")

                    with col2:
                        if st.button("Delete", key=f"del_{row['id']}", type="secondary"):
                            delete_citation(row["id"])
                            st.rerun()

                    st.divider()
                    
                    folder_choices = {"Unassigned": None}
                    for f in user_folders:
                        folder_choices[f["name"]] = f["id"]
                    
                    current_folder_id = row["folder_id"]
                    current_folder_index = 0
                    if current_folder_id:
                        for idx, (fname, fid) in enumerate(folder_choices.items()):
                            if fid == current_folder_id:
                                current_folder_index = idx
                                break

                    selected_folder_name = st.selectbox(
                        "Folder Assignment",
                        options=list(folder_choices.keys()),
                        index=current_folder_index,
                        key=f"folder_select_{row['id']}"
                    )
                    updated_folder_id = folder_choices[selected_folder_name]

                    current_note = row["notes"] or ""
                    new_note = st.text_area(
                        "Citation Notes",
                        value=current_note,
                        key=f"note_{row['id']}",
                        height=100
                    )
                    
                    if new_note != current_note or updated_folder_id != current_folder_id:
                        if st.button("Update Record", key=f"save_note_{row['id']}"):
                            update_citation_folder_and_notes(row["id"], updated_folder_id, new_note)
                            st.success("Record updated!")
                            st.rerun()

    # --- TAB 3: EXPORT ---
    with tab_export:
        st.subheader("Export Citations")
        records = get_user_citations(user_id, selected_folder_id)

        if not records:
            st.info("No citations available to export.")
        else:
            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                export_format = st.radio("Select Output Format:", ["Raw Text List", "Include Notes", "CSV Table"])
            with col_exp2:
                sort_alphabetical = st.checkbox("Alphabetize by First Author Surname (A-Z)", value=True)

            if sort_alphabetical:
                records.sort(key=lambda x: get_first_author_surname(x["authors"]))

            formatted_output = ""
            if export_format == "Raw Text List":
                formatted_output = "\n\n".join([r["raw_text"] for r in records])
            elif export_format == "Include Notes":
                formatted_output = "\n\n".join([
                    f"{r['raw_text']}\nNote: {r['notes']}" if r['notes'] else r['raw_text']
                    for r in records
                ])
            elif export_format == "CSV Table":
                df = pd.DataFrame(records)
                # Drop raw internal object column from CSV output if present
                if "folders" in df.columns:
                    df = df.drop(columns=["folders"])
                formatted_output = df.to_csv(index=False)

            st.text_area("Ready to Copy:", value=formatted_output, height=300)
            st.caption("Click inside the text area, press Ctrl+A / Cmd+A, then Ctrl+C / Cmd+C to copy directly to your clipboard.")