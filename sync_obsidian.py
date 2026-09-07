import os
import shutil
import yaml

OBSIDIAN_PLACES = r'D:\DataBases\mstr_obs_git\02-Projects\02-Sightseeing\Places'
QUARTZ_CONTENT = r'C:\Users\Kirill\sightseeing-site\content'

def is_public(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        if not content.startswith('---'):
            return False
        try:
            # Extract YAML frontmatter
            parts = content.split('---', 2)
            if len(parts) < 3:
                return False
            metadata = yaml.safe_load(parts[1])
            tags = metadata.get('tags', [])
            return 'public' in tags
        except Exception:
            return False

def sync():
    if not os.path.exists(QUARTZ_CONTENT):
        os.makedirs(QUARTZ_CONTENT)
    
    for filename in os.listdir(OBSIDIAN_PLACES):
        if filename.endswith('.md'):
            src_path = os.path.join(OBSIDIAN_PLACES, filename)
            if is_public(src_path):
                dst_path = os.path.join(QUARTZ_CONTENT, filename)
                shutil.copy2(src_path, dst_path)
                print(f"Synced: {filename}")

if __name__ == "__main__":
    sync()
