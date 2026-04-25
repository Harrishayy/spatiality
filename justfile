default:
    @just --list

# One-shot env setup (uv workspace: shared, capture, inference, segmentation)
setup:
    uv sync

# Generate the stub scene Devin builds against
stub-scene:
    uv run python scripts/make_stub_scene.py

# Module entrypoints (stubs in Session A; real impl in Sessions B/C)
capture scene_id="test_scene_v0":
    uv run python -m capture --scene-id {{scene_id}}

infer scene_id="test_scene_v0":
    uv run python -m inference --scene-id {{scene_id}}

segment scene_id="test_scene_v0":
    uv run python -m segmentation --scene-id {{scene_id}}

# Round-trip every JSON/YAML artifact through pydantic
check scene_id="test_scene_v0":
    uv run python shared/scripts/validate.py artifacts/scenes/{{scene_id}}

# End-to-end smoke (all stubs back-to-back)
smoke: stub-scene capture infer segment check

# Modal skeleton deploy (succeeds even without GPU work wired)
modal-deploy:
    uv run modal deploy inference/modal_app.py

# ─── Kaggle workflow ──────────────────────────────────────────────────────
# Build the bundle (wheels + VGGT + 3DGRUT + weights + repo snapshot). 5-30 min, ~6GB.
bundle video="":
    bash bundle/build_bundle.sh {{video}}

# Push (or version) the bundle as a Kaggle dataset. Heavy upload (~6GB).
push-bundle:
    cd bundle && \
      if kaggle datasets list --mine 2>/dev/null | grep -q glasses-twin-bundle; then \
        kaggle datasets version -p . -m "rebuild $(date +%Y-%m-%dT%H:%M)" --dir-mode zip; \
      else \
        kaggle datasets create -p . --dir-mode zip; \
      fi

# Push the kernel (small).
push-kernel:
    cd kernel && kaggle kernels push

# Block until the kernel finishes, then download outputs to ./output/
run-kernel:
    @echo "polling kaggle kernels status (Ctrl-C to detach)…"
    @while true; do \
      status=$$(kaggle kernels status harrishayyanar/glasses-twin-run 2>/dev/null | grep -oE '"[^"]+"' | head -1 | tr -d '"'); \
      echo "$$(date +%H:%M:%S)  $$status"; \
      case "$$status" in \
        complete) break;; \
        error|cancelAcknowledged) echo "FAILED: $$status"; exit 1;; \
      esac; \
      sleep 15; \
    done
    mkdir -p output
    kaggle kernels output harrishayyanar/glasses-twin-run -p output/

# Build, push, run, pull — the whole loop. Heavy.
kaggle-loop: bundle push-bundle push-kernel run-kernel
