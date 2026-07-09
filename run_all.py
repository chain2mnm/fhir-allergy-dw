# run the three steps in order, stop if one fails

import subprocess
import sys

steps = ["load_stage.py", "load_dim.py", "load_fact.py"]

for step in steps:
    print("")
    result = subprocess.run([sys.executable, step])
    if result.returncode != 0:
        print(step + " failed, stopping")
        sys.exit(1)

print("")
print("pipeline finished ok")
