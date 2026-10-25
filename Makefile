.PHONY: test install uninstall zip
test:
	python3 -m unittest discover -s tests -v
install:
	./install.sh
uninstall:
	./uninstall.sh
zip:
	cd .. && zip -r leapsh.zip leapsh -x '*/__pycache__/*' '*.pyc'
