# Code Learner Third-Party Notices

## Universal Ctags

Code Learner can build and execute the pinned Universal Ctags source located at
`third_party/universal-ctags`. Universal Ctags is licensed under GNU GPL v2.
Its complete copyright notices and license text are preserved in the pinned
submodule, including `COPYING` and `COPYING.rst`.

ElectroBoy invokes the resulting executable as a separate process. The
Universal Ctags source and executable are not incorporated into the ElectroBoy
Python modules. A distribution that bundles the executable must also bundle
the corresponding pinned source, copyright notices, and license text.

## Jansson

Code Learner builds the pinned Jansson source at `third_party/jansson` as a
private static dependency when it builds Universal Ctags with JSON support.
Jansson is licensed under the MIT license, with additional notices for specific
source files. Its complete notices and license text are preserved in the pinned
submodule's `LICENSE` file.
