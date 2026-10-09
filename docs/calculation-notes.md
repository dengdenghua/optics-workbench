# Calculation definitions

These equations are implemented directly in `optics_workbench/calculations.py`. Inputs and outputs are conditions for first-order design, not measured performance. Lengths are millimetres, angles degrees, wavelength nanometres, and photometric flux lumens. Refractive index must correspond to the chosen wavelength; changing wavelength does not update a material or lens catalog automatically.

## Collimation

For source width `w`, collection half-angle `u`, target output half-angle `v` in air:

```
q_x = w sin(u)
matched_output_width = q_x / sin(v)
first_order_focal_estimate = w / (2 tan(v))
predicted_half_angle = atan(w / (2 reference_EFL))
```

Apply independently in X and Y. These are separable invariant and finite-source thin-lens starting relations; they do not define the same surface or guarantee realizability. Real high-NA collection requires principal-plane, aperture, aberration and source-position checks. Source-side normal-axis étendue for rectangular area `A` and a circular cone is `G = pi A sin(u)^2` for `n=1`; the axis estimates are not a full 4D phase-space matching proof.

## Flyeye

For clear cell dimensions `a_x, a_y` and effective focal lengths:

```
m = relay_EFL / cell_EFL
image_width = a_x m
required_width = target_width + 2 margin
coverage_x = image_width / required_width
minimum_relay_EFL = max(required_width/a_x, required_height/a_y) cell_EFL
nominal_array_span_x = columns pitch_x
FN_x = (a_x/2)^2 / (wavelength_nm * 1e-6 * cell_EFL)
```

Coverage tests the ideal rectangle in both dimensions; `FN` is a dimensionless diagnostic without a pass/fail threshold. Actual lenslet spacing, two-array alignment, clear aperture, transition zones, pupil matching, diffraction and uniformity remain outside the calculation.

## Interface margin

For nonabsorbing dielectric media with `n_high > n_low`, the critical angle is `asin(n_low/n_high)`. Internal incidence is measured from the normal of that particular interface.

- Intended reflection clearance: `minimum_internal_incidence - critical_angle`.
- Intended transmission clearance: `critical_angle - maximum_internal_incidence`.

Clearance must be **strictly greater** than the requested margin, with a `1e-10 degree` equality tolerance. This only checks a given interface angle envelope. Coatings, Fresnel transmission, dispersion envelopes, air-gap thickness, frustrated TIR and polarization are not solved. PBS reports unknown for this check.

## Photometric budget

For an ideal Lambertian source, the collected fraction of forward hemispherical flux within half-angle `u` is `sin(u)^2`. A custom fraction is a user assumption. Collection applies once to source lumens, followed by user-supplied collimator, flyeye, prism, imager and projection-lens factors.

These factors must have compatible denominators and must not already include the same losses. Geometry warnings do not invent an additional efficiency. No spectral conversion, RGB chromaticity, ANSI lumens, laser safety, screen gain or luminance calculation is performed. A positive budget is not proof of optical feasibility.
