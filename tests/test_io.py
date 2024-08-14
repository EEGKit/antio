from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from mne import Annotations
from mne.io import read_raw_brainvision
from numpy.testing import assert_allclose

from antio.io import read_raw_ant

if TYPE_CHECKING:
    from mne.io import BaseRaw


def read_raw_bv(fname: Path) -> BaseRaw:
    """Read a brainvision file exported from eego."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Limited .* annotation.*outside the data range.",
            category=RuntimeWarning,
        )
        raw_bv = read_raw_brainvision(fname)
    return raw_bv


@pytest.fixture()
def ca_208() -> dict[str, dict[str, Path]]:
    """Return the paths to the CA_208 dataset containing 64 channel gel recordings."""
    directory = Path(__file__).parent / "data" / "CA_208"
    cnt = {
        "short": directory / "test_CA_208.cnt",
        "amp-dc": directory / "test_CA_208_amp_disconnection.cnt",
        "start-stop": directory / "test_CA_208_start_stop.cnt",
    }
    bv = {key: value.with_suffix(".vhdr") for key, value in cnt.items()}
    return {"cnt": cnt, "bv": bv}


def test_io_data(ca_208: dict[str, dict[str, Path]]) -> None:
    """Test loading of .cnt file."""
    raw_cnt = read_raw_ant(ca_208["cnt"]["short"])
    raw_bv = read_raw_bv(ca_208["bv"]["short"])
    cnt = raw_cnt.get_data()
    bv = raw_bv.get_data()
    assert cnt.shape == bv.shape
    assert_allclose(raw_cnt.get_data(), raw_bv.get_data(), atol=1e-8)


def test_io_info(ca_208: dict[str, dict[str, Path]]) -> None:
    """Test the info loaded from a .cnt file."""
    raw_cnt = read_raw_ant(ca_208["cnt"]["short"])
    raw_bv = read_raw_bv(ca_208["bv"]["short"])
    assert raw_cnt.ch_names == raw_bv.ch_names
    assert raw_cnt.info["sfreq"] == raw_bv.info["sfreq"]
    assert raw_cnt.get_channel_types() == ["eeg"] * 64 + ["misc"] * 24
    with pytest.warns(
        RuntimeWarning,
        match="All EEG channels are not referenced to the same electrode.",
    ):
        raw_cnt = read_raw_ant(ca_208["cnt"]["short"], misc=None)
    assert raw_cnt.get_channel_types() == ["eeg"] * len(raw_cnt.ch_names)
    raw_cnt = read_raw_ant(ca_208["cnt"]["short"], eog="EOG")
    idx = raw_cnt.ch_names.index("EOG")
    ch_types = ["eeg"] * 64 + ["misc"] * 24
    ch_types[idx] = "eog"
    assert raw_cnt.get_channel_types() == ch_types


def test_io_amp_disconnection(ca_208: dict[str, dict[str, Path]]) -> None:
    """Test loading of .cnt file with amplifier disconnection."""
    raw_cnt = read_raw_ant(ca_208["cnt"]["amp-dc"])
    raw_bv = read_raw_bv(ca_208["bv"]["amp-dc"])
    assert_allclose(raw_cnt.get_data(), raw_bv.get_data(), atol=1e-8)
    assert (
        raw_cnt.get_data(reject_by_annotation="omit").shape != raw_bv.get_data().shape
    )
    # create annotation on the BV file
    idx = [
        k
        for k, elt in enumerate(raw_bv.annotations.description)
        if any(code in elt for code in ("9001", "9002"))
    ]
    assert len(idx) == 2
    start = raw_bv.annotations.onset[idx[0]]
    stop = raw_bv.annotations.onset[idx[1]]
    annotations = Annotations(
        onset=start,
        duration=stop - start + 1 / raw_bv.info["sfreq"],  # estimate is 1 sample short
        description="BAD_segment",
    )
    raw_bv.set_annotations(annotations)
    assert_allclose(
        raw_cnt.get_data(reject_by_annotation="omit"),
        raw_bv.get_data(reject_by_annotation="omit"),
        atol=1e-8,
    )
