# SPDX-License-Identifier: GPL-3.0-or-later
import fw_hil


def test_package_imports():
    assert fw_hil.__version__ == "0.1.0"
