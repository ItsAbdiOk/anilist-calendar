import requests
import datetime
import time

# --- CONFIGURATION ---
USERNAME = "TheBastard" 
OUTPUT_FILENAME = "my_manga_history.ics"
MINUTES_PER_CHAPTER = 4
# ---------------------

URL = "https://graphql.anilist.co"

def get_user_id(username):
    query = """
    query ($name: String) {
        User (name: $name) { id }
    }
    """
    response = requests.post(URL, json={'query': query, 'variables': {'name': username}})
    data = response.json()
    if 'errors' in data:
        raise Exception(f"User '{username}' not found.")
    return data['data']['User']['id']

def get_manga_history(user_id):
    print(f"Fetching history for User ID: {user_id}...")
    
    query = """
    query ($userId: Int, $page: Int) {
        Page (page: $page, perPage: 50) {
            pageInfo { hasNextPage }
            activities (userId: $userId, type: MEDIA_LIST, sort: ID_DESC) {
                ... on ListActivity {
                    id
                    createdAt
                    progress
                    status
                    media {
                        id
                        title { romaji english }
                        type
                    }
                }
            }
        }
    }
    """
    
    page = 1
    all_activities = []
    
    while True:
        print(f"Fetching page {page}...", end='\r')
        time.sleep(0.5) 
        
        try:
            response = requests.post(URL, json={'query': query, 'variables': {'userId': user_id, 'page': page}})
            
            if response.status_code == 429:
                time.sleep(60)
                continue
                
            data = response.json()
            if 'errors' in data: break
            
            page_data = data['data']['Page']
            activities = page_data['activities']
            
            if not activities: break

            for activity in activities:
                if not activity.get('media'): continue
                if activity['media']['type'] == 'MANGA':
                    # We accept ALL entries now, because we will parse the strings manually
                    all_activities.append(activity)
            
            if not page_data['pageInfo']['hasNextPage']: break
            page += 1
            
        except Exception as e:
            print(f"Error on page {page}: {e}")
            break
        
    print(f"\nFound {len(all_activities)} manga entries.")
    return all_activities

def format_date_ics(timestamp):
    dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    return dt.strftime('%Y%m%dT%H%M%SZ')

def parse_progress(val):
    """
    Parses 'progress' which might be an int (122) or a string range ("111 - 121").
    Returns the END number of the range.
    """
    if val is None: return 0
    
    # If it's already a number
    if isinstance(val, (int, float)):
        return int(val)
        
    # If it's a string (e.g., "111 - 121")
    val_str = str(val).strip()
    
    if '-' in val_str:
        try:
            # Split "111 - 121", take "121", clean it, convert to int
            parts = val_str.split('-')
            return int(parts[-1].strip())
        except ValueError:
            return 0
            
    # Fallback for normal string numbers
    try:
        return int(val_str)
    except ValueError:
        return 0

def generate_ics(activities, filename):
    print(f"Generating {filename}...")
    
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AniList History Export//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    
    # 1. Sort by ID (Strictly Oldest -> Newest)
    activities.sort(key=lambda x: x['id'])

    progress_tracker = {} 
    time_tracker = {'global_last_end': 0}

    for act in activities:
        media_id = act['media']['id']
        title = act['media']['title']['english'] or act['media']['title']['romaji'] or "Unknown Title"
        status = act['status']
        
        # --- THE FIX: Use the new parser ---
        current_progress = parse_progress(act['progress'])
        previous_progress = parse_progress(progress_tracker.get(media_id, 0))
        
        # Calculate chapters read
        if current_progress > previous_progress:
            chapters_read = current_progress - previous_progress
            
            # Logic: If gap is huge (imported library) or 0 (re-read), default to 1
            # We increased the limit to 500 to handle your binge sessions (e.g. 11-121 is valid)
            if previous_progress == 0 and chapters_read > 500:
                chapters_read = 1
        else:
            chapters_read = 1

        if chapters_read < 1: chapters_read = 1

        # Calculate Duration
        duration_minutes = chapters_read * MINUTES_PER_CHAPTER
        duration_seconds = duration_minutes * 60
        
        # --- Smart Time Shifting ---
        original_start = act['createdAt']
        calculated_start = original_start
        
        last_busy_until = time_tracker['global_last_end']
        
        # If overlap happens within 2 hours, push it forward
        if calculated_start < last_busy_until:
             if (last_busy_until - calculated_start) < 7200:
                calculated_start = last_busy_until + 1
        
        calculated_end = calculated_start + duration_seconds
        
        # Update trackers
        if current_progress > 0:
            progress_tracker[media_id] = current_progress
        
        time_tracker['global_last_end'] = calculated_end

        # Generate Event Summary
        if status == 'COMPLETED':
            summary = f"Completed: {title}"
        elif current_progress:
            if chapters_read > 1:
                # e.g. "Read Dungeon Reset (Ch. 111-121)"
                summary = f"Read {title} (Ch. {previous_progress + 1}-{current_progress})"
            else:
                summary = f"Read {title} Ch. {current_progress}"
        else:
            continue

        dt_start = format_date_ics(calculated_start)
        dt_end = format_date_ics(calculated_end)
        
        event_block = [
            "BEGIN:VEVENT",
            f"UID:anilist-{act['id']}@anilist.co",
            f"DTSTAMP:{dt_start}",
            f"DTSTART:{dt_start}",
            f"DTEND:{dt_end}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:Read {chapters_read} chapters. Duration: {duration_minutes} mins.",
            "END:VEVENT"
        ]
        ics_lines.extend(event_block)
        
    ics_lines.append("END:VCALENDAR")
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(ics_lines))
        
    print("Done! File created successfully.")

if __name__ == "__main__":
    try:
        u_id = get_user_id(USERNAME)
        history = get_manga_history(u_id)
        generate_ics(history, OUTPUT_FILENAME)
    except Exception as e:
        print(f"Error: {e}")