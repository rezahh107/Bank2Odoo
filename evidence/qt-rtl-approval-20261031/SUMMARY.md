# Real-product Qt UI diagnostic — synthetic Windows QPA

Base: 5d4b950c29a73433c043a53dc266cee9192d3de4
OS: Windows-2025Server-10.0.26100-SP0; Qt: 6.11.2; QPA: windows
Theme selection is an application-only test override, not an OS preference measurement.

- rtl_baseline_light_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_horizontal_ltr_light_940x830: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_baseline_light_650x520: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_horizontal_ltr_light_650x520: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_baseline_light_600x480: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_horizontal_ltr_light_600x480: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- checkbox_baseline_light_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=2.073; border_fraction_3=0.0329
- checkbox_unscoped_rule_light_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=2.073; border_fraction_3=0.0329
- checkbox_bright_border_light_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=2.073; border_fraction_3=0.0329
- checkbox_negative_light_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=2.073; border_fraction_3=0.0329
- rtl_baseline_dark_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_horizontal_ltr_dark_940x830: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_baseline_dark_650x520: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_horizontal_ltr_dark_650x520: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_baseline_dark_600x480: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- rtl_horizontal_ltr_dark_600x480: error=none; order_ok=True; horizontal_scroll=0; unchecked_border_p95=None; border_fraction_3=None
- checkbox_baseline_dark_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=13.925; border_fraction_3=0.5526
- checkbox_unscoped_rule_dark_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=13.925; border_fraction_3=0.5526
- checkbox_bright_border_dark_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=5.573; border_fraction_3=0.5526
- checkbox_negative_dark_940x830: error=none; order_ok=False; horizontal_scroll=0; unchecked_border_p95=1.01; border_fraction_3=0.0

No production patch or physical Windows 11 acceptance. See measurements.json and original-resolution PNGs.
