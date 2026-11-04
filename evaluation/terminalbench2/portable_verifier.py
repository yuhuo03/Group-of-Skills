"""Harbor import target; loaded only when portable verifier assets are selected."""
from harbor.verifier.verifier import Verifier
from goskills_eval.terminalbench2.dependency_transport import verifier_class


class PortableVerifier(Verifier):
    def __new__(cls, *args, assets_config, **kwargs):
        implementation = verifier_class(Verifier, assets_config)
        return implementation(*args, **kwargs)
