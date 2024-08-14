from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np

from .libeep import read_cnt
from .utils._checks import ensure_path
from .utils._imports import import_optional_dependency

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Optional, Union

    from numpy.typing import NDArray

    from .libeep import InputCNT

import_optional_dependency("mne")

from mne import Annotations, create_info  # noqa: E402
from mne.io import BaseRaw  # noqa: E402
from mne.utils import copy_doc, fill_doc, logger, verbose, warn  # noqa: E402

units = {"uv": 1e-6}


@fill_doc
class RawANT(BaseRaw):
    r"""Reader for Raw ANT files in .cnt format.

    Parameters
    ----------
    fname : str | Path
        Path to the ANT raw file to load. The file should have the extension ``.cnt``.
    eog : str | None
        Regex pattern to find EOG channel labels. If None, no EOG channels are
        automatically detected.
    misc : str | None
        Regex pattern to find miscellaneous channels. If None, no miscellaneous channels
        are automatically detected. The default pattern ``"BIP\d+"`` will mark all
        bipolar channels as ``misc``.

        .. note::

            A bipolar channel might actually contain ECG, EOG or other signal types
            which might have a dedicated channel type in MNE-Python. In this case, use
            :meth:`mne.io.Raw.set_channel_types` to change the channel type of the
            channel.
    %(verbose)s
    """

    @verbose
    def __init__(
        self,
        fname: Union[str, Path],
        eog: Optional[str],
        misc: Optional[str],
        verbose=None,
    ) -> None:
        logger.info("Reading ANT file %s", fname)
        fname = ensure_path(fname, must_exist=True)
        cnt = read_cnt(str(fname))
        # parse channels, sampling frequency, and create info
        ch_names, ch_units, ch_refs, ch_types = _parse_channels(cnt, eog, misc)
        info = create_info(
            ch_names, sfreq=cnt.get_sample_frequency(), ch_types=ch_types
        )
        data = _parse_data(cnt, ch_units)  # read data array
        super().__init__(info, preload=data, filenames=[fname], verbose=verbose)
        # look for annotations (called trigger by ant)
        onsets, durations, descriptions, _ = _parse_triggers(cnt)
        onsets = np.array(onsets) / self.info["sfreq"]
        durations = np.array(durations) / self.info["sfreq"]
        annotations = Annotations(onsets, duration=durations, description=descriptions)
        self.set_annotations(annotations)


def _parse_channels(
    cnt: InputCNT, eog: Optional[str], misc: Optional[str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Parse the channel names annd attempt to find channel type."""
    n_channels = cnt.get_channel_count()
    ch_names, ch_units, ch_refs, ch_types = [], [], [], []
    eog = re.compile(eog) if eog is not None else None
    misc = re.compile(misc) if misc is not None else None
    for k in range(n_channels):
        ch_curr = cnt.get_channel(k)
        ch_names.append(ch_curr[0])
        ch_units.append(ch_curr[1].lower())  # always lower the unit for mapping
        ch_refs.append(ch_curr[2])
        if eog is not None and re.fullmatch(eog, ch_curr[0]):
            ch_types.append("eog")
        elif misc is not None and re.fullmatch(misc, ch_curr[0]):
            ch_types.append("misc")
        else:
            ch_types.append("eeg")
    if len(set(ch_refs)) == 1:
        logger.info("All %i channels are referenced to %s.", len(ch_refs), ch_refs[0])
    else:
        warn("All channels are not referenced to the same electrode.")
    return ch_names, ch_units, ch_refs, ch_types


def _parse_data(cnt: InputCNT, ch_units: list[str]) -> NDArray[np.float64]:
    """Parse the data array."""
    n_channels = cnt.get_channel_count()
    n_samples = cnt.get_sample_count()  # sample = (n_channels,)
    data = cnt.get_samples(0, n_samples)
    data = np.array(data).reshape(n_channels, -1).T  # (n_channels, n_samples)
    # apply scalings to SI units if able
    units_index = defaultdict(list)
    for idx, unit in enumerate(ch_units):
        units_index[unit].append(idx)
    for unit, value in units_index.items():
        if unit in units:
            data[np.array(value, dtype=np.int16), :] *= units[unit]
        else:
            warn(f"Unit {unit} not recognized, not scaling.")
    return data


def _parse_triggers(
    cnt: InputCNT,
) -> tuple[list[int], list[int], list[str], dict[int, list[float]]]:
    """Parse triggers into annotations."""
    n_triggers = cnt.get_trigger_count()
    onsets, durations, descriptions = [], [], [], []
    impedances = dict()
    disconnect = dict(start=[], stop=[])
    for k in range(n_triggers):
        code, idx, duration, condition, description, impedance = cnt.get_trigger(k)
        # detect impedance measurements
        if (
            description is not None
            and description.lower() == "impedance"
            and impedance is not None
        ):
            impedances[idx] = [float(elt) for elt in impedance.split(" ")]
            # create a BAD_impedance annotation to mark the bad segment
            onsets.append(idx)
            durations.append(duration)
            description.append("BAD_impedance")
            continue
        # detect amplifier disconnection
        if condition is not None and condition.lower() == "amplifier disconnected":
            disconnect["start"].append(idx)
            continue
        elif condition is not None and condition.lower() == "amplifier reconnected":
            disconnect["stop"].append(idx)
            continue
        # treat all the other triggers as regular event annotations
        onsets.append(idx)
        durations.append(duration)
        if description is not None:
            descriptions.append(description)
        else:
            descriptions.append(code)
    return onsets, durations, descriptions, impedances


@copy_doc(RawANT)
def read_raw_ant(
    fname: Union[str, Path],
    eog: Optional[str] = None,
    misc: Optional[str] = r"BIP\d+",
    verbose=None,
) -> RawANT:
    return RawANT(fname, eog=eog, misc=misc, verbose=verbose)
