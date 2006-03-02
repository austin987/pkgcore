#!/bin/bash
rm -rf ~/vdb-{install,test}
mkdir ~/vdb-test
python -c'import portage.config;from portage.vdb import repository;v=repository("/home/bharring/vdb-test").trees[0];
v.frozen=False;
i=v.install(portage.config.load_config().domain["livefs domain"].repos[0]["dev-util/bsdiff-4.3"].build().finalize(), 
	offset="/home/bharring/vdb-install");
i.finish();'
