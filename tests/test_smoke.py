# SPDX-License-Identifier: GPL-3.0-or-later
import fw_hil


def test_package_imports():
    assert fw_hil.__version__ == "0.1.0"


def test_public_api_surface():
    import fw_hil

    assert callable(fw_hil.analyze_loopback)
    assert callable(fw_hil.generate_sine)
    assert callable(fw_hil.assert_composite)
    assert callable(fw_hil.run_update_cycle)
    assert callable(fw_hil.run_revert_cycle)
    assert fw_hil.LoopbackResult is not None
    assert fw_hil.UpdateResult is not None
    assert fw_hil.BenchDriver is not None
    assert fw_hil.STLinkBackend is not None
    assert fw_hil.ExpectedComposite.fm_board().uac2_sample_rate_hz == 8000
