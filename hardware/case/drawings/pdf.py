import glob, ezdxf
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
from ezdxf import bbox
from ezdxf.fonts import fonts
if hasattr(fonts, "build_font_manager_cache"): fonts.build_font_manager_cache(Path.home() / ".cache/ezdxf_fonts")
with PdfPages(str(Path(__file__).resolve().parent / "out" / "ESS01-CASE_도면_A3.pdf")) as pdf:
    for f in sorted(glob.glob(str(Path(__file__).resolve().parent / "out" / "*.dxf"))):
        doc = ezdxf.readfile(f)
        doc.styles.get("KOR").dxf.font = "NanumGothic.ttf"
        msp = doc.modelspace()
        frame = max((e for e in msp.query("LWPOLYLINE[layer=='FRAME']")), key=lambda e: bbox.extents([e]).size.x)
        ext = bbox.extents([frame])
        fig = plt.figure(figsize=(16.535, 11.693))       # A3 가로 (인치)
        ax = fig.add_axes([0, 0, 1, 1])
        cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK)
        Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(msp, finalize=True)
        ax.set_xlim(ext.extmin.x, ext.extmax.x); ax.set_ylim(ext.extmin.y, ext.extmax.y); ax.set_aspect("equal")
        pdf.savefig(fig); plt.close(fig)
        print(Path(f).name)
