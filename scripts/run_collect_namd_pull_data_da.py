"""
write nc file which contains
'zF_t', 'wF_t', 'zR_t', 'wR_t', 'ks',
'lambda_F', 'lambda_R', 'pulling_times', 'dt'
"""

import os
import argparse

import numpy as np
import netCDF4 as nc

from _IO import save_to_nc

parser = argparse.ArgumentParser()

parser.add_argument("--pull_dir", type=str, default="20A_per_2ns")

parser.add_argument("--range", type=str,  default="0 200")
parser.add_argument("--f_b_breakpoint", type=int,  default=10)

parser.add_argument("--exclude", type=str,  default=" ")

parser.add_argument("--pulling_speed", type=float,  default=0.01) # Angstrom per ps = speed in A per step / (2*10**(-3))
parser.add_argument("--force_constant", type=float,  default=7.2) # kcal/mol/A^2
parser.add_argument("--lambda_range", type=str,  default="13. 33.")

parser.add_argument( "--take_only_half",            action="store_true", default=False)

parser.add_argument("--ntrajs_per_block", type=int,  default=10)
parser.add_argument("--out", type=str,  default="pull_data.nc")

args = parser.parse_args()

KB = 0.0019872041   # kcal/mol/K
TEMPERATURE = 300.
BETA = 1/KB/TEMPERATURE

FORWARD_FORCE_FILE = "forward.force"
BACKWARD_FORCE_FILE = "backward.force"


def _time_z_work(tcl_force_out_file, pulling_speed):
    """
    :param tcl_force_out_file: str, file name
    :param pulling_speed: float, Angstrom per ps
    :return: (pulling_times, z_t, w_t) in (ps, Angstrom, kcal/mol)
    """
    data = np.loadtxt(tcl_force_out_file)

    pulling_times = data[:, 0]
    z_t = data[:, 1]
    forces = data[:, 2]

    nsteps = len(pulling_times)

    w_t = np.zeros([nsteps], dtype=float)
    dts = pulling_times[1:] - pulling_times[:-1]

    w_t[1:] = pulling_speed * forces[:-1] * dts
    w_t = np.cumsum(w_t)

    return pulling_times, z_t, w_t


def _lambda_t(pulling_times, pulling_speed, z0):
    """
    :param pulling_times: ndarray of float, ps
    :param pulling_speed: float, Angstrom per ps
    :param z0: float, Angstrom
    :return: lambda_t, ndarray of float
    """
    lambda_t = pulling_times*pulling_speed + z0
    return lambda_t


def _combine_forward_backward(forward_force_file, backward_force_file,
                              pulling_speed,
                              lambda_min, lambda_max):
    t_F, zF_t, wF_t = _time_z_work(forward_force_file, pulling_speed)
    t_R, zR_t, wR_t = _time_z_work(backward_force_file, - pulling_speed)

    lambda_F = _lambda_t(t_F, pulling_speed, lambda_min)
    lambda_R = _lambda_t(t_R, - pulling_speed, lambda_max)
    lambda_t = np.concatenate( (lambda_F, lambda_R[1:]) )

    pulling_times = np.concatenate( (t_F, t_R[1:] + t_F[-1]) )
    z_t = np.concatenate( (zF_t, zR_t[1:]) )
    w_t = np.concatenate( (wF_t, wR_t[1:] + wF_t[-1]) )
    return pulling_times, lambda_t, z_t, w_t


def _take_only_forward(forward_force_file, pulling_speed, lambda_min):
    t_F, zF_t, wF_t = _time_z_work(forward_force_file, pulling_speed)
    lambda_t = _lambda_t(t_F, pulling_speed, lambda_min)
    pulling_times = t_F
    z_t = zF_t
    w_t = wF_t
    return pulling_times, lambda_t, z_t, w_t

# -----------

ks = 100. * BETA * args.force_constant
lambda_min = float(args.lambda_range.split()[0])
lambda_max = float(args.lambda_range.split()[1])

start = int(args.range.split()[0])
end = int(args.range.split()[1])

exclude = [int(s) for s in args.exclude.split()]
print("exclude", exclude)

indices_to_collect = [i for i in range(start, end) if i not in exclude]
forward_files = [os.path.join(args.pull_dir, "%d"%i, FORWARD_FORCE_FILE) for i in indices_to_collect]
backward_files = [os.path.join(args.pull_dir, "%d"%i, BACKWARD_FORCE_FILE) for i in indices_to_collect]

if args.take_only_half:
    pulling_times, lambda_t, z_t, w_t = _take_only_forward(forward_files[0], args.pulling_speed, lambda_min)
else:
    pulling_times, lambda_t, z_t, w_t = _combine_forward_backward(forward_files[0], backward_files[0],
                                                              args.pulling_speed, lambda_min, lambda_max)


dt = pulling_times[1] - pulling_times[0]
nsteps = pulling_times.shape[0]
assert len(forward_files) %  args.ntrajs_per_block == 0, "total number of data files must be multiple of ntrajs_per_block"
nrepeats = len(forward_files) / args.ntrajs_per_block


z_ts = np.zeros([nrepeats, args.ntrajs_per_block, nsteps], dtype=float)
w_ts = np.zeros([nrepeats, args.ntrajs_per_block, nsteps], dtype=float)


icount = -1
for repeat in range(nrepeats):
    for traj in range(args.ntrajs_per_block):
        icount += 1
        print "loading ", icount

        if args.take_only_half:
            _, _, z_t, w_t = _take_only_forward(forward_files[icount], args.pulling_speed, lambda_min)

        else:
            _, _, z_t, w_t = _combine_forward_backward(forward_files[icount], backward_files[icount],
                                                   args.pulling_speed, lambda_min, lambda_max)
        z_ts[repeat, traj, :] = z_t
        w_ts[repeat, traj, :] = w_t

lambda_t /= 10.            # to nm
z_ts     /= 10.            # to nm
w_ts     = w_ts*BETA       # kcal/mol to KT/mol

out_nc_handle = nc.Dataset(args.out, "w", format="NETCDF4")

data = {"dt" : np.array([dt], dtype=float),
        "pulling_times" : pulling_times,
        "ks" : np.array([ks]),
        "lambda_F" : lambda_t,
        "wF_t" : w_ts[ : args.f_b_breakpoint, :, :],
        "zF_t" : z_ts[ : args.f_b_breakpoint, :, :],

        "lambda_R": lambda_t,
        "wR_t" : w_ts[args.f_b_breakpoint :, :, :],
        "zR_t" : z_ts[args.f_b_breakpoint :, :, :],
        }

save_to_nc(data, out_nc_handle)
out_nc_handle.close()

print("DONE")