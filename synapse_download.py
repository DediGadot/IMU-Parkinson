import synapseclient
import synapseutils
import os

TOKEN = os.environ["SYNAPSE_TOKEN"]

syn = synapseclient.Synapse()
syn.login(authToken=TOKEN)

# List contents first
children = list(syn.getChildren("syn55052683"))
print(f"Children in syn55052683: {len(children)}")
for c in children:
    print(f"  {c['name']} ({c['type']}) - {c['id']}")

# Download everything
print("\nStarting download...")
files = synapseutils.syncFromSynapse(syn, "syn55052683", path="/root/pd-imu/data/raw/weargait-pd")
print(f"\nDownload complete. Files: {len(files)}")
