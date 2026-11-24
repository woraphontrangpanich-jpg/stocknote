import os
import tempfile

# keep tests away from the real ledger in ./data
os.environ["STOCKNOTE_DATA"] = tempfile.mkdtemp(prefix="stocknote-test-")
