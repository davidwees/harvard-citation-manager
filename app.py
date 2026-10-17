import sqlite3
import re
import hashlib
import streamlit as st
import pandas as pd

# Database Setup
DB_FILE = "citations.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS citations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                folder_id INTEGER,
                raw_text TEXT NOT NULL,
                authors TEXT,
                year TEXT,
                title TEXT,
                source TEXT,
                url TEXT,
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE SET NULL
            )
        """)
        conn.commit()

# Helper Functions: Auth
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, hash_password(password))
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def authenticate_user(username, password):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ? AND password_hash = ?",
            (username, hash_password(password))
        ).fetchone()

# Helper Functions: Citation Parsing & Sorting
def parse_harvard_citation(text):
    """
    Regex parser for basic Harvard format patterns.
    Pattern target: Authors (Year) Title. Source. Available at: URL
    """
    clean_text = text.strip()
    
    # Extract URL if present
    url_match = re.search(r'Available at:\s*(https?://[^\s]+)', clean_text, re.IGNORECASE)
    url = url_match.group(1).rstrip('.') if url_match else ""
    
    # Remove URL part for further parsing
    main_text = re.sub(r'Available at:\s*https?://[^\s]+', '', clean_text, flags=re.IGNORECASE).strip()

    # Extract Authors and Year: Author(s) (Year or 'no date')
    author_year_match = re.match(r'^(.*?)\s*\((.*?)\)(.*)$', main_text)
    
    if author_year_match:
        authors = author_year_match.group(1).strip()
        year = author_year_match.group(2).strip()
        rest = author_year_match.group(3).strip()
        
        # Split rest into Title and Source by first major punctuation
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
    """
    Extracts the first author's surname for sorting purposes.
    Handles formats like 'Siddiqui & Wardle', 'Siddiqui, A. and Wardle, B.', or 'BERA'.
    """
    if not authors_str or not authors_str.strip():
        return "ZZZ_UNKNOWN"  # Push empty authors to the end
    
    # Get the first author before connectors like '&', 'and', or commas separating multiple authors
    first_author = re.split(r'\s+and\s+|\s*&\s*|;', authors_str, flags=re.IGNORECASE)[0].strip()
    
    if ',' in first_author:
        # Format: Surname, Initial(s)
        surname = first_author.split(',')[0].strip()
    else:
        # Format: Firstname Surname or single word organization name
        words = [w for w in first_author.split() if not w.endswith('.')]
        surname = words[-1] if words else first_author
        
    return surname.lower()

# Folder CRUD
def create_folder(user_id, folder_name):
    with get_connection() as conn:
        conn.execute("INSERT INTO folders (user_id, name) VALUES (?, ?)", (user_id, folder_name.strip()))
        conn.commit()

def get_user_folders(user_id):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM folders WHERE user_id = ? ORDER BY name ASC", (user_id,)).fetchall()

def delete_folder(folder_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        conn.commit()

# Citation CRUD Operations
def save_citation(user_id, parsed_data, folder_id=None, notes=""):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO citations (user_id, folder_id, raw_text, authors, year, title, source, url, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            folder_id,
            parsed_data["raw_text"],
            parsed_data["authors"],
            parsed_data["year"],
            parsed_data["title"],
            parsed_data["source"],
            parsed_data["url"],
            notes
        ))
        conn.commit()

def get_user_citations(user_id, folder_id=None):
    with get_connection() as conn:
        if folder_id is not None:
            return conn.execute(
                "SELECT c.*, f.name as folder_name FROM citations c LEFT JOIN folders f ON c.folder_id = f.id WHERE c.user_id = ? AND c.folder_id = ? ORDER BY c.id ASC",
                (user_id, folder_id)
            ).fetchall()
        else:
            return conn.execute(
                "SELECT c.*, f.name as folder_name FROM citations c LEFT JOIN folders f ON c.folder_id = f.id WHERE c.user_id = ? ORDER BY c.id ASC",
                (user_id,)
            ).fetchall()

def update_citation_folder_and_notes(citation_id, folder_id, notes):
    with get_connection() as conn:
        conn.execute(
            "UPDATE citations SET folder_id = ?, notes = ? WHERE id = ?",
            (folder_id, notes, citation_id)
        )
        conn.commit()

def delete_citation(citation_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM citations WHERE id = ?", (citation_id,))
        conn.commit()


# App Interface
st.set_page_config(page_title="Harvard Citation Manager", page_icon="📚", layout="wide")
init_db()

if "user" not in st.session_state:
    st.session_state.user = None

# Sidebar Authentication & Folder Management
st.sidebar.title("👤 User Account")

if st.session_state.user is None:
    auth_mode = st.sidebar.radio("Select Action", ["Login", "Register"])
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")

    if auth_mode == "Register":
        if st.sidebar.button("Register"):
            if username and password:
                if register_user(username, password):
                    st.sidebar.success("Account created successfully! Please log in.")
                else:
                    st.sidebar.error("Username already exists.")
            else:
                st.sidebar.warning("Please fill in both fields.")
    else:
        if st.sidebar.button("Login"):
            user = authenticate_user(username, password)
            if user:
                st.session_state.user = dict(user)
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
    
    # Folder creation in sidebar
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
            st.sidebar.warning("Folder deleted (citations moved to Unassigned).")
            st.rerun()

# Main Application Content
st.title("📚 Harvard Citation Manager")

if st.session_state.user is None:
    st.info("Please log in or register from the sidebar to manage your citations.")
else:
    user_id = st.session_state.user["id"]
    user_folders = get_user_folders(user_id)

    # Tab Layout
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
                st.success("Citation added successfully!")
                st.rerun()
            else:
                st.warning("Please paste a citation before saving.")

    # --- TAB 2: MANAGE CITATIONS & NOTES ---
    with tab_view:
        view_title = f"Citations ({selected_folder_label})"
        st.subheader(view_title)
        
        records = get_user_citations(user_id, selected_folder_id)

        if not records:
            st.info("No citations found for this folder view.")
        else:
            # Convert SQLite rows to dicts for sorting
            records_list = [dict(r) for r in records]
            
            sort_by_author = st.checkbox("Sort display by First Author Surname (A-Z)", value=True)
            if sort_by_author:
                records_list.sort(key=lambda x: get_first_author_surname(x["authors"]))

            for row in records_list:
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
                    
                    # Folder and Note editing block
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
                            st.success("Record updated successfully!")
                            st.rerun()

    # --- TAB 3: EXPORT ---
    with tab_export:
        st.subheader("Export Citations")
        records = get_user_citations(user_id, selected_folder_id)

        if not records:
            st.info("No citations available to export for this selection.")
        else:
            records_list = [dict(r) for r in records]

            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                export_format = st.radio("Select Output Format:", ["Raw Text List", "Include Notes", "CSV Table"])
            with col_exp2:
                sort_alphabetical = st.checkbox("Alphabetize by First Author Surname (A-Z)", value=True)

            if sort_alphabetical:
                records_list.sort(key=lambda x: get_first_author_surname(x["authors"]))

            formatted_output = ""
            if export_format == "Raw Text List":
                formatted_output = "\n\n".join([r["raw_text"] for r in records_list])
            elif export_format == "Include Notes":
                formatted_output = "\n\n".join([
                    f"{r['raw_text']}\nNote: {r['notes']}" if r['notes'] else r['raw_text']
                    for r in records_list
                ])
            elif export_format == "CSV Table":
                df = pd.DataFrame(records_list)
                formatted_output = df.to_csv(index=False)

            st.text_area("Ready to Copy:", value=formatted_output, height=300)
            st.caption("Click inside the text area, press Ctrl+A / Cmd+A, then Ctrl+C / Cmd+C to copy directly to your clipboard.")