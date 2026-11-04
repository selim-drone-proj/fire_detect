import sys, glob, ezdxf, os
from pathlib import Path
from ezdxf.fonts import fonts
fonts.build_font_manager_cache(Path.home() / ".cache/ezdxf_fonts") if hasattr(fonts, "build_font_manager_cache") else None
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
os.makedirs(Path(__file__).resolve().parent / "out" / "png", exist_ok=True)
for f in sorted(glob.glob(str(Path(__file__).resolve().parent / "out" / "*.dxf"))):
    doc = ezdxf.readfile(f)
    doc.styles.get("KOR").dxf.font = "NanumGothic.ttf"
    fig = plt.figure(figsize=(16.54, 11.69))
    ax = fig.add_axes([0, 0, 1, 1])
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK, lineweight_scaling=1.0)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace())
    out = str(Path(f).parent / "png" / (Path(f).stem + ".png"))
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(out)
